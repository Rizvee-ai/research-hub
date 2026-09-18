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

# How much of each document is sent. Kept small because the app and
# the embedding model share one small container, and loading whole
# documents was crashing it.
CHARS_PER_DOC = 6000


def client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Check your .env file.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def generate(prompt, model=None, attempts=5):
    """
    One call to Gemini, retried when Google is busy.

    A 503 means their servers are overloaded and a 429 means a rate
    limit was touched — both clear on their own. Giving up on the first
    one puts an error in front of the person asking, when waiting a few
    seconds would have worked.
    """
    import time

    last = None
    for attempt in range(attempts):
        try:
            return client().models.generate_content(
                model=model or GEMINI_MODEL, contents=prompt
            ).text
        except Exception as e:
            last = e
            text = str(e)
            transient = ("503" in text or "UNAVAILABLE" in text
                         or "429" in text or "overloaded" in text.lower())
            if not transient or attempt == attempts - 1:
                raise
            time.sleep(15 * (attempt + 1))    # 15s, 30s, 45s, 60s
    raise last


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


def generate(topic, kind="review", doc_type=None, label=None, limit=6):
    """
    kind is "brief" or "review".
    Returns (text, documents_used).
    """
    docs = db.documents_by_filter(doc_type=doc_type, topic=label, limit=limit)

    if not docs:
        return ("No documents in the collection match that filter, "
                "so there is nothing to summarise."), []

    # Built a piece at a time, dropping each document's text once it
    # has been added. Holding all of them in memory at once was enough
    # to kill the process on a small container — the app would die
    # rather than return an error.
    parts = []
    for i, d in enumerate(docs, start=1):
        head = f"[{i}] {d['title'] or 'Untitled'}"
        if d["authors"]:
            head += f" — {d['authors']}"
        if d["doc_date"]:
            head += f" ({d['doc_date']})"
        parts.append(head + "\n" + (d["full_text"] or "")[:CHARS_PER_DOC])
        d["full_text"] = None          # not needed again

    body = "\n\n".join(parts)
    del parts

    template = BRIEF if kind == "brief" else REVIEW
    prompt = template.format(topic=topic, documents=body, n=len(docs))

    text = generate(prompt)

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
