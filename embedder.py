"""
Turning text into numbers.

Each passage becomes a list of 384 numbers positioned so that
passages about similar things end up with similar numbers —
which is what lets a search for "paramedic burnout" find a
document that says "exhaustion in ambulance staff".

This runs on our own machine. No API, no cost, no rate limit.
It is the highest-volume operation in the system, which is
exactly why it does not go through a paid service.

The model is loaded once and reused. Loading it per request
would exhaust the memory of a small host.
"""

from sentence_transformers import SentenceTransformer

from config import EMBEDDING_MODEL

_model = None


def model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed_many(texts, show_progress=True):
    """For ingestion — many passages at once."""
    return model().encode(
        texts,
        batch_size=32,
        show_progress_bar=show_progress,
        convert_to_numpy=True,
    )


def embed_one(text):
    """For a question at search time."""
    return model().encode(text, convert_to_numpy=True)


def to_sql(vector):
    """pgvector wants the literal form '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"
