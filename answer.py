"""
Turning retrieved passages into a written answer with sources.

The important detail is what the model is not given. It sees
numbered passages and nothing else — no titles, no authors, no
dates, no links. So it has no material from which to invent a
reference. Every citation in the finished answer is built by the
code below, from the database rows that produced the passages.

That makes a fabricated source structurally impossible rather
than merely discouraged.
"""

import re

from google import genai

import search
from config import (GEMINI_API_KEY, GEMINI_MODEL, TOP_K, MIN_SIMILARITY)

_client = None


def client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Check your .env file.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


TEMPLATE = """Answer the question using ONLY the passages below.

Mark every claim with the number of the passage it came from, like [1].
If a claim draws on more than one, mark them all, like [1][3].

If the passages do not answer the question, say so plainly. Do not fill
gaps from general knowledge. Do not overstate a tentative finding.

{context}

Question: {question}
"""

NOTHING_FOUND = (
    "Nothing in the collection addresses that. "
    "The documents held do not cover this, so there is no answer to give."
)


def ask(question, doc_type=None, topic=None):
    """
    Returns (answer_text, sources).
    sources is the list of passages the answer was built from.
    """
    # Is anything close enough to be worth answering from?
    if search.best_similarity(question, doc_type, topic) < MIN_SIMILARITY:
        return NOTHING_FOUND, []

    hits = search.search(question, k=TOP_K, doc_type=doc_type, topic=topic)
    if not hits:
        return NOTHING_FOUND, []

    context = "\n\n".join(
        f"[{i}] {h['text']}" for i, h in enumerate(hits, start=1)
    )

    text = client().models.generate_content(
        model=GEMINI_MODEL,
        contents=TEMPLATE.format(context=context, question=question),
    ).text

    return resolve_citations(text, hits), hits


def resolve_citations(text, hits):
    """Replace [1] with a real reference, looked up from our own records."""
    def reference(match):
        n = int(match.group(1))
        if not 1 <= n <= len(hits):
            return match.group(0)
        h = hits[n - 1]
        name = h["title"] or h["filename"]
        bits = [name]
        if h["authors"]:
            bits.append(h["authors"])
        if h["doc_date"]:
            bits.append(str(h["doc_date"]))
        if h["page"] and h["page"] > 1:
            bits.append(f"p.{h['page']}")
        return "(" + ", ".join(bits) + ")"

    return re.sub(r"\[(\d+)\]", reference, text)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "What is the approach to psychological safety?"
    print(f"\nQ: {q}\n")
    text, sources = ask(q)
    print(text)
    if sources:
        print("\n" + "-" * 60)
        for i, s in enumerate(sources, start=1):
            print(f"[{i}] {s['title'] or s['filename']}  p.{s['page']}")
