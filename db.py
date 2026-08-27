"""Everything that touches the database lives here."""

import json
import psycopg
from psycopg.rows import dict_row

from config import DATABASE_URL


def connect():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Check your .env file."
        )
    return psycopg.connect(DATABASE_URL, row_factory=dict_row,
                           prepare_threshold=None)


# ─── writing ─────────────────────────────────────────────────────

def already_ingested(content_hash):
    """True if we have seen this exact file before."""
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM documents WHERE content_hash = %s",
            (content_hash,),
        ).fetchone()
        return row is not None


def insert_document(filename, content_hash, source_path, page_count,
                    word_count, full_text, meta, status="ingested",
                    status_note=None):
    with connect() as conn:
        row = conn.execute(
            """
            INSERT INTO documents
                (filename, content_hash, source_path, page_count, word_count,
                 full_text, title, authors, doc_date, doc_type, audience,
                 topics, summary, key_points, status, status_note)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                filename, content_hash, source_path, page_count, word_count,
                full_text,
                meta.get("title"), meta.get("authors"), meta.get("date"),
                meta.get("doc_type"), meta.get("audience"),
                meta.get("topics") or [],
                meta.get("summary"), meta.get("key_points"),
                status, status_note,
            ),
        ).fetchone()
        conn.commit()
        return row["id"]


def insert_chunks(doc_id, chunks, vectors):
    """chunks is a list of {page, seq, text}; vectors matches it in order."""
    with connect() as conn:
        with conn.cursor() as cur:
            for ch, vec in zip(chunks, vectors):
                cur.execute(
                    """
                    INSERT INTO chunks (doc_id, page, seq, text, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (doc_id, ch["page"], ch["seq"], ch["text"],
                     "[" + ",".join(f"{x:.6f}" for x in vec) + "]"),
                )
        conn.commit()


def record_excluded(filename, content_hash, source_path, reason):
    """A document we could not use. Recorded so it does not vanish."""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO documents
                (filename, content_hash, source_path, status, status_note)
            VALUES (%s, %s, %s, 'excluded', %s)
            ON CONFLICT (content_hash) DO NOTHING
            """,
            (filename, content_hash, source_path, reason),
        )
        conn.commit()


# ─── reading ─────────────────────────────────────────────────────

def all_documents():
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, title, filename, doc_date, doc_type, audience,
                   topics, summary, page_count, word_count, status,
                   reviewed_by, added_at
            FROM documents
            ORDER BY added_at DESC
            """
        ).fetchall()


def documents_by_filter(doc_type=None, topic=None, limit=25):
    """Used by briefs and reviews to pick which documents to read whole."""
    with connect() as conn:
        return conn.execute(
            """
            SELECT id, title, authors, doc_date, full_text
            FROM documents
            WHERE status = 'ingested'
              AND full_text IS NOT NULL
              AND (%s IS NULL OR doc_type = %s)
              AND (%s IS NULL OR %s = ANY(topics))
            ORDER BY word_count DESC
            LIMIT %s
            """,
            (doc_type, doc_type, topic, topic, limit),
        ).fetchall()


def counts():
    with connect() as conn:
        docs = conn.execute(
            "SELECT status, COUNT(*) AS n FROM documents GROUP BY status"
        ).fetchall()
        chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        return {r["status"]: r["n"] for r in docs}, chunks["n"]


def mark_reviewed(doc_id, who):
    with connect() as conn:
        conn.execute(
            "UPDATE documents SET reviewed_by = %s WHERE id = %s",
            (who, doc_id),
        )
        conn.commit()
