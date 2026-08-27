"""
Briefs and reviews.

These do not use passage retrieval. A question needs the handful of
passages that answer it; a summary of a topic needs a fair
representation of everything relevant.

Picking the best-matching passages favours whichever documents phrase
a topic most fluently, so a review built that way is drawn from three
documents while reading as though it covered twenty.

So: filter by label to choose the documents, then send them whole.
"""

from google import genai

import db
from config import GEMINI_API_KEY, GEMINI_MODEL

_client = None


def client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Check your .env file.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


BRIEF = """Write a short briefing on: {topic}

Use ONLY the documents below. Structure it as:

  What we have on this
  Key points
  What follows from it
  Sources

Keep it to about a page — it is for someone deciding something, not
researching it. Mark claims with the document number, like [3]. Where
documents disagree, say so. Where the material is thin, say that too.

{documents}
"""

REVIEW = """Write a structured review on: {topic}

Use ONLY the documents below. Structure it as:

  Background
  What the material says
  Where it is thin or absent
  Sources

Mark claims with the document number, like [3]. Where documents
disagree, say so rather than picking a side. Any statement about
gaps must be framed as a gap in these {n} documents, not as a gap
in the field.

{documents}
"""


def generate(topic, kind="review", doc_type=None, label=None, limit=20):
    """
    kind is "brief" or "review".
    Returns (text, documents_used).
    """
    docs = db.documents_by_filter(doc_type=doc_type, topic=label, limit=limit)

    if not docs:
        return ("No documents in the collection match that filter, "
                "so there is nothing to summarise."), []

    body = "\n\n".join(
        f"[{i}] {d['title'] or 'Untitled'}"
        f"{' — ' + d['authors'] if d['authors'] else ''}"
        f"{' (' + str(d['doc_date']) + ')' if d['doc_date'] else ''}\n"
        f"{(d['full_text'] or '')[:30000]}"
        for i, d in enumerate(docs, start=1)
    )

    template = BRIEF if kind == "brief" else REVIEW
    prompt = template.format(topic=topic, documents=body, n=len(docs))

    text = client().models.generate_content(
        model=GEMINI_MODEL, contents=prompt
    ).text

    # resolve the numbers to real references, in code
    for i, d in enumerate(docs, start=1):
        name = d["title"] or "Untitled"
        ref = f"({name}{', ' + str(d['doc_date']) if d['doc_date'] else ''})"
        text = text.replace(f"[{i}]", ref)

    note = (f"\n\n---\nBuilt from {len(docs)} document"
            f"{'s' if len(docs) != 1 else ''} in the collection.")

    return text + note, docs
