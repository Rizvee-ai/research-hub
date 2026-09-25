"""
Settings for the AI Research Hub.

The three values in the block below decide how text is turned into
numbers. Passages and questions must be turned into numbers the same
way, by the same model, or the comparison between them is meaningless
— and it fails quietly, giving plausible results that are wrong rather
than an error.

So they cannot be changed on their own. Changing one means re-cutting
and re-embedding every document, which rechunk.py does: it works from
the text already stored, so nothing is downloaded, transcribed or
labelled again, and no Gemini call is made. Twenty minutes, locally.

Change these here, then run rechunk.py to bring the collection into
line. Never one without the other.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── change these only together with a run of rechunk.py ─────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # 384 dimensions
CHUNK_WORDS     = 250
CHUNK_OVERLAP   = 40
# ─────────────────────────────────────────────────────────────────

# How many passages an answer is built from.
#
# Tied to CHUNK_WORDS: the model should see roughly the same amount of
# text either way. Eight passages of 600 words and twenty of 250 are
# about the same volume, drawn from twenty places rather than eight.
TOP_K = 20

# Below this, the collection is treated as not covering the question,
# and nothing is generated at all.
#
# Measured rather than guessed, with:  python run_cases.py calibrate
# That scores questions the collection does cover against questions it
# cannot, and puts the floor between them. Re-run it after any change
# to the block above: passages of a different size score differently,
# and a floor set for the old size will either refuse real questions
# or let unanswerable ones through.
MIN_SIMILARITY = 0.48

GEMINI_MODEL = "gemini-3.1-flash-lite"

# secrets, read from .env — never hard-code these
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")

# where the PDFs and Word files live
DOCS_DIR = os.getenv("DOCS_DIR", "documents")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")


# ─── fixed lists ─────────────────────────────────────────────────
# The model picks from these rather than inventing labels, so the
# same idea does not become three different tags. Every list ends
# in "Other" so a document that genuinely does not fit is labelled
# honestly rather than forced into the nearest wrong category.

DOC_TYPES = [
    "Research paper",
    "Report",
    "Course or training material",
    "Framework or model",
    "Proposal or quote",
    "Meeting notes",
    "Marketing or promotional",
    "Form or template",
    "Administrative record",
    "Other",
]

AUDIENCES = [
    "Internal team",
    "Client or prospective client",
    "Course participants",
    "General public",
    "Unclear",
]

TOPICS = [
    "Resilience",
    "Recovery and trauma",
    "Leadership",
    "Psychological safety",
    "Coaching",
    "Sensemaking and decision making",
    "Team culture",
    "Training delivery",
    "Business operations",
    "Other",
]
