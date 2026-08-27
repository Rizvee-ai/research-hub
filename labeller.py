"""
Asking the model to fill in a record for each document.

Two rules in the prompt do most of the work:

  "return null rather than guess" — a plausible invented date is
  worse than a blank one, because nobody checks a field that looks
  reasonable.

  "choose exactly one of the following" — free text fragments, and
  the same idea becomes three different tags. Every list ends in
  "Other" so a document that genuinely does not fit is labelled
  honestly.
"""

import json
import re
import time

from google import genai

from config import (GEMINI_API_KEY, GEMINI_MODEL,
                    DOC_TYPES, AUDIENCES, TOPICS)

_client = None


def client():
    global _client
    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Check your .env file.")
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


PROMPT = """You are cataloguing a document for an internal library.

Return a JSON object with exactly these keys:

  title       the document's title, or a short descriptive one if it has none
  authors     who wrote or issued it, or null
  date        the date on the document as written, or null
  doc_type    exactly one of: {doc_types}
  audience    exactly one of: {audiences}
  topics      one to three of: {topics}
  summary     two or three sentences on what this document is and contains
  key_points  three to five short bullet lines, separated by newlines

Rules:
- If something is not stated in the document, use null. Do not guess.
- doc_type, audience and topics must be chosen from the lists above,
  copied exactly. Use "Other" or "Unclear" if nothing fits.
- Return JSON only. No markdown fences, no commentary.

DOCUMENT:
{text}
"""


def label(text, retries=3):
    """Returns a dict of metadata. Raises on repeated failure."""
    prompt = PROMPT.format(
        doc_types=" | ".join(DOC_TYPES),
        audiences=" | ".join(AUDIENCES),
        topics=" | ".join(TOPICS),
        text=text[:60000],          # generous, but bounded
    )

    last = None
    for attempt in range(retries):
        try:
            raw = client().models.generate_content(
                model=GEMINI_MODEL, contents=prompt
            ).text
            return _parse(raw)
        except Exception as e:
            last = e
            # rate limits and transient errors: wait and try again
            time.sleep(5 * (attempt + 1))

    raise RuntimeError(f"labelling failed after {retries} attempts: {last}")


def _parse(raw):
    """The model is told to return bare JSON, but be forgiving about fences."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(),
                     flags=re.MULTILINE).strip()
    data = json.loads(cleaned)

    # keep the fixed lists honest even if the model strays
    if data.get("doc_type") not in DOC_TYPES:
        data["doc_type"] = "Other"
    if data.get("audience") not in AUDIENCES:
        data["audience"] = "Unclear"

    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = [topics]
    data["topics"] = [t for t in topics if t in TOPICS] or ["Other"]

    if isinstance(data.get("key_points"), list):
        data["key_points"] = "\n".join(data["key_points"])

    return data
