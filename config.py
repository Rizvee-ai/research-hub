"""
Settings for the AI Research Hub.

The first three values are fixed for the life of the project.
Changing them later means re-processing every document, because
passages and questions must be turned into numbers by the same
model, in the same way, or the comparison is meaningless.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── fixed in week one, do not change ────────────────────────────
EMBEDDING_MODEL = "all-MiniLM-L6-v2"   # 384 dimensions
CHUNK_WORDS     = 600
CHUNK_OVERLAP   = 90
# ─────────────────────────────────────────────────────────────────

# how much readable text a document needs before we accept it
MIN_WORDS_PER_DOC  = 200
MIN_WORDS_PER_PAGE = 25

# how many passages an answer is built from
TOP_K = 8

# below this, we treat the collection as not covering the question
MIN_SIMILARITY = 0.25

GEMINI_MODEL = "gemini-3.6-flash"

# secrets, read from .env — never hard-code these
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DATABASE_URL   = os.getenv("DATABASE_URL")

# where the PDFs and Word files live
DOCS_DIR = os.getenv("DOCS_DIR", "documents")


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
