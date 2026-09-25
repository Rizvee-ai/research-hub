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

def by_name(question, k=None, doc_type=None, topic=None):
    """
    Finding a document by its name rather than its contents.

    The passage index is built from passage text, so a title or an
    author that is recorded against a document but never printed
    inside it cannot be matched. That is why searching a paper's own
    title returned it first less than half the time, and why an
    author's surname almost never worked.

    A match here returns the document's opening passage, which anchors
    the document into the results. If a better passage exists, the
    other two searches will surface it.
    """
    k = k or TOP_K

    where, filter_params = _filters(doc_type, topic)

    sql = f"""
        SELECT c.id, c.doc_id, c.page, c.text,
               d.title, d.authors, d.doc_date, d.filename,
               ts_rank(d.doc_tsv, plainto_tsquery('english', %s)) AS score
        FROM documents d
        JOIN LATERAL (
            SELECT id, doc_id, page, text FROM chunks
            WHERE doc_id = d.id ORDER BY seq LIMIT 1
        ) c ON true
        WHERE d.status = 'ingested'
          AND d.doc_tsv @@ plainto_tsquery('english', %s){where}
        ORDER BY score DESC
        LIMIT %s
    """
    with db.connect() as conn:
        return conn.execute(
            sql, (question, question, *filter_params, k)
        ).fetchall()










def search(question, k=None, doc_type=None, topic=None):
    """
    Merge the result sets by rank rather than by score, because the
    scores are not on the same scale and cannot be compared directly.
    A passage near the top of more than one list scores better.

    The name search is weighted higher than the other two. Someone
    typing a document's title or an author's surname is telling us
    which document they want, and that is a far less ambiguous signal
    than a passage happening to sit close by in meaning.
    """
    k = k or TOP_K

    lists = [
        (semantic(question, doc_type=doc_type, topic=topic), 1.0),
        (keyword(question, doc_type=doc_type, topic=topic), 1.0),
        (by_name(question, doc_type=doc_type, topic=topic), 2.0),
    ]

    scores, rows = {}, {}
    for results, weight in lists:
        for rank, row in enumerate(results, start=1):
            scores[row["id"]] = scores.get(row["id"], 0) + weight / (60 + rank)
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
