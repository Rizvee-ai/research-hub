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


def semantic(question, k=None, doc_type=None, topic=None):
    k = k or TOP_K * 2
    vec = embedder.to_sql(embedder.embed_one(question))

    sql = """
        SELECT c.id, c.doc_id, c.page, c.text,
               d.title, d.authors, d.doc_date, d.filename,
               1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.doc_id
        WHERE d.status = 'ingested'
          AND (%s::text IS NULL OR d.doc_type = %s::text)
          AND (%s::text IS NULL OR %s::text = ANY(d.topics))
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    with db.connect() as conn:
        return conn.execute(
            sql, (vec, doc_type, doc_type, topic, topic, vec, k)
        ).fetchall()


def keyword(question, k=None, doc_type=None, topic=None):
    k = k or TOP_K * 2

    sql = """
        SELECT c.id, c.doc_id, c.page, c.text,
               d.title, d.authors, d.doc_date, d.filename,
               ts_rank(c.tsv, plainto_tsquery('english', %s)) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.doc_id
        WHERE d.status = 'ingested'
          AND c.tsv @@ plainto_tsquery('english', %s)
          AND (%s::text IS NULL OR d.doc_type = %s::text)
          AND (%s::text IS NULL OR %s::text = ANY(d.topics))
        ORDER BY score DESC
        LIMIT %s
    """
    with db.connect() as conn:
        return conn.execute(
            sql, (question, question, doc_type, doc_type, topic, topic, k)
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
