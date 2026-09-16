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

    text = resolve_citations(text, docs)

    # a plain list of what was actually read, with the real filename
    # and a link, so any claim can be checked against the source
    lines = [f"\n\n---\n\n**Read from {len(docs)} document"
             f"{'s' if len(docs) != 1 else ''}:**\n"]
    for i, d in enumerate(docs, start=1):
        name = d["title"] or d.get("filename") or "Untitled"
        line = f"{i}. {name}"
        if d.get("filename") and d["filename"] != name:
            line += f"  \n    *file:* `{d['filename']}`"
        if d.get("source_path", "").startswith("http"):
            line += f"  \n    [open in Drive]({d['source_path']})"
        lines.append(line)

    return text + "\n".join(lines), docs


def resolve_citations(text, docs):
    """
    Turn [3] and [1, 2] into document names.

    Done in descending numeric order, because replacing [1] first
    would corrupt [12] and [19]. Handles grouped markers as well as
    single ones.
    """
    import re

    def name_of(n):
        if not 1 <= n <= len(docs):
            return None
        d = docs[n - 1]
        name = d["title"] or d.get("filename") or "Untitled"
        if d.get("doc_date"):
            name += f", {d['doc_date']}"
        return name

    def replace(match):
        numbers = [int(x) for x in re.findall(r"\d+", match.group(0))]
        names = [name_of(n) for n in numbers]
        names = [n for n in names if n]
        if not names:
            return match.group(0)
        # keep it readable when several documents support one claim
        if len(names) > 2:
            return f"({names[0]}, and {len(names) - 1} others)"
        return "(" + "; ".join(names) + ")"

    # [1, 2, 7] and [4] alike
    return re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", replace, text)
