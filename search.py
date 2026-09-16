"""
Finding the passages most likely to bear on a question.

Two searches run and their results are merged:

  by meaning  — finds a paper about "exhaustion in ambulance staff"
                when you searched "paramedic burnout"

  by exact words — finds a document when you search its actual title,
                which meaning-based search alone is surprisingly bad at

A passage found by either method surfaces; one found by both rises
further. Because everything lives in one database, both searches and
any filters resolve in a single round trip.
"""

import db
import embedder
from config import TOP_K


def _filters(doc_type, topic):
    """
    Build the filter clause from whatever is actually set.

    Passing NULL and testing for it inside the SQL leaves Postgres
    unable to work out the parameter's type, which fails outright.
    Adding the clause only when there is something to filter on
    avoids the problem rather than casting around it.
    """
    clauses, params = [], []
    if doc_type:
        clauses.append("d.doc_type = %s")
        params.append(doc_type)
    if topic:
        clauses.append("%s = ANY(d.topics)")
        params.append(topic)
    return ("".join(f"\n          AND {c}" for c in clauses), params)


def semantic(question, k=None, doc_type=None, topic=None):
    k = k or TOP_K * 2
    vec = embedder.to_sql(embedder.embed_one(question))
    where, filter_params = _filters(doc_type, topic)

    sql = f"""
        SELECT c.id, c.doc_id, c.page, c.text,
               d.title, d.authors, d.doc_date, d.filename,
               1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.doc_id
        WHERE d.status = 'ingested'{where}
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    with db.connect() as conn:
        return conn.execute(
            sql, (vec, *filter_params, vec, k)
        ).fetchall()


def keyword(question, k=None, doc_type=None, topic=None):
    k = k or TOP_K * 2

    where, filter_params = _filters(doc_type, topic)

    sql = f"""
        SELECT c.id, c.doc_id, c.page, c.text,
               d.title, d.authors, d.doc_date, d.filename,
               ts_rank(c.tsv, plainto_tsquery('english', %s)) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.doc_id
        WHERE d.status = 'ingested'
          AND c.tsv @@ plainto_tsquery('english', %s){where}
        ORDER BY score DESC
        LIMIT %s
    """
    with db.connect() as conn:
        return conn.execute(
            sql, (question, question, *filter_params, k)
        ).fetchall()


def search(question, k=None, doc_type=None, topic=None):
    """
    Merge the two result sets by rank rather than by score, because
    the two scores are not on the same scale and cannot be compared
    directly. A passage near the top of either list scores well; one
    near the top of both scores better.
    """
    k = k or TOP_K

    a = semantic(question, doc_type=doc_type, topic=topic)
    b = keyword(question, doc_type=doc_type, topic=topic)

    scores, rows = {}, {}
    for results in (a, b):
        for rank, row in enumerate(results, start=1):
            scores[row["id"]] = scores.get(row["id"], 0) + 1 / (60 + rank)
            rows[row["id"]] = row

    best = sorted(scores, key=scores.get, reverse=True)[:k]
    return [rows[i] for i in best]


def best_similarity(question, doc_type=None, topic=None):
    """
    How close is the nearest passage? Used to decide whether the
    collection covers the question at all, before the model is asked.
    """
    hits = semantic(question, k=1, doc_type=doc_type, topic=topic)
    return hits[0]["score"] if hits else 0.0
