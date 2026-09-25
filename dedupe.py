"""
Finding works that are in the collection more than once.

    python dedupe.py            show what it would do, change nothing
    python dedupe.py --apply    carry it out

Exact copies are already caught during ingestion by hashing the file, so
what is left is the harder kind: the same work saved twice. A book as
final proofs and again as a copy-edited draft. A tender response as a
.docx and again as a .pdf. A report exported once more under a different
name. Different bytes, different hash, same words.

These are not harmless. The Resilience by Design book is in three times,
so a review that reads ten documents may really be reading seven works,
and an answer can cite the same passage twice as though two sources
agreed. Retrieval spends slots on material it already has.

Two passes:

  identical text   the extracted words are the same once spacing and
                   case are set aside. Catches the same document saved
                   in two formats.

  same work        the text itself is nearly the same. Catches drafts,
                   proofs and re-exports, where extraction differs
                   slightly but the work does not.

The second pass compares content, not titles. Titles here were written
by the model, so two different proposals to two different clients get
near-identical ones, and grouping on that alone proposed dropping real
documents — a different tender lot, a different course session, a
different person's photograph. Titles now only decide which pairs are
worth comparing; the text decides whether they are the same.

Images are left alone entirely. Their titles are descriptions the model
wrote from the picture, so every headshot resembles every other one,
and there is no text to compare instead.

The copy with the most words is kept, on the grounds that it is the
least truncated. The others are marked 'duplicate' and their passages
are removed, which takes them out of search and gives the space back.
Nothing is deleted from the record: every duplicate keeps its row, its
filename and a note naming the copy that was kept, so the decision can
be read back and reversed.
"""

import re
import sys
from collections import defaultdict

import db

APPLY = "--apply" in sys.argv

# How much two titles must overlap before the pair is worth comparing.
# This only shortlists candidates; it never decides anything by itself.
TITLE_OVERLAP = 0.8

# How close in length, as a fraction of the longer one.
LENGTH_TOLERANCE = 0.25

# How much of the text must match before two documents are the same
# work. Measured on overlapping runs of eight words, so a shared
# sentence counts and a shared vocabulary does not.
TEXT_OVERLAP = 0.85

# Length of those runs.
SHINGLE = 8

# Pictures are excluded. Their titles describe what is in them, so
# every headshot looks like a duplicate of every other headshot, and
# they hold no text to settle it with.
PICTURES = {".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff",
            ".webp", ".bmp", ".heic", ".heif", ".svg"}

# Groups holding any file whose name contains one of these are left
# alone, however alike their text is.
#
# A quotation and a tender lot are records before they are reading
# matter. Two lots of one tender are ninety-nine per cent the same
# words and are still two documents somebody may have to produce. And
# a copy taken out of search is not merely ranked lower — its passages
# are gone, so no search of any kind can reach it again. That is the
# right trade for a brochure printed six ways and the wrong one here.
#
# Add to this list rather than arguing with the similarity threshold.
KEEP_APART = [
    "Tender Response Document",
    "Quotation_Form_FrontlineMind",
    "CPHS Startegic planning",
    "Planning Day Summary",
]

# Words too common to carry any weight in a title comparison.
NOISE = {"a", "an", "the", "and", "or", "of", "in", "to", "for", "on",
         "with", "at", "by", "from", "how", "what", "is", "are", "be",
         "this", "that", "final", "draft", "copy", "v1", "v2", "v3",
         "rev", "revised", "edited", "latest", "new", "old", "version"}


def title_words(title):
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return {w for w in words if w not in NOISE and len(w) > 2}


def overlap(a, b):
    """How much two sets share, as a fraction of the smaller one."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def held_back(group):
    """The reason this group is being left alone, or None."""
    for d in group:
        for fragment in KEEP_APART:
            if fragment.lower() in (d["filename"] or "").lower():
                return fragment
    return None


def is_picture(filename):
    name = (filename or "").lower()
    return any(name.endswith(ext) for ext in PICTURES)


def shingles(text):
    """
    The set of overlapping eight-word runs in a document.

    Comparing these rather than single words is what separates two
    copies of one report from two reports about the same subject. The
    second pair shares a vocabulary; only the first shares sentences.
    """
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    if len(words) < SHINGLE:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + SHINGLE])
            for i in range(len(words) - SHINGLE + 1)}


def close_in_length(a, b):
    longer = max(a or 0, b or 0)
    if not longer:
        return False
    return abs((a or 0) - (b or 0)) / longer <= LENGTH_TOLERANCE


def load():
    """
    Everything except the text, which is far too much to hold at once.
    The hash is computed in the database instead, and the text itself
    is fetched later only for the handful of pairs worth comparing.
    """
    with db.connect() as conn:
        return conn.execute(
            """
            SELECT id, filename, title, word_count, page_count,
                   md5(regexp_replace(lower(coalesce(full_text, '')),
                                      '\\s+', ' ', 'g')) AS text_hash
            FROM documents
            WHERE status = 'ingested' AND full_text IS NOT NULL
            ORDER BY id
            """
        ).fetchall()


def texts(ids):
    """The text of specific documents, fetched in one go."""
    if not ids:
        return {}
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, left(full_text, 200000) AS full_text "
            "FROM documents WHERE id = ANY(%s)",
            (list(ids),),
        ).fetchall()
    return {r["id"]: r["full_text"] for r in rows}


def best_of(group):
    """The copy to keep: most words, then most pages, then earliest in."""
    return sorted(group,
                  key=lambda d: (-(d["word_count"] or 0),
                                 -(d["page_count"] or 0),
                                 d["id"]))[0]


def group_by_text(docs):
    """Pass one — the extracted words are identical."""
    buckets = defaultdict(list)
    for d in docs:
        buckets[d["text_hash"]].append(d)
    return [g for g in buckets.values() if len(g) > 1]


def group_by_work(docs, already):
    """
    Pass two — the text is nearly the same.

    Two steps. Titles and lengths shortlist the pairs worth looking at,
    because comparing every document with every other one would mean
    holding the whole collection in memory. Then the text of only those
    documents is fetched and compared properly.

    A pair joins a group only if it clears TEXT_OVERLAP. Two proposals
    to two clients share a template and a title and fail this; two
    exports of one report pass it.
    """
    remaining = [d for d in docs
                 if d["id"] not in already and not is_picture(d["filename"])]
    words = {d["id"]: title_words(d["title"]) for d in remaining}

    # Which pairs are worth reading.
    candidates = []
    for i, a in enumerate(remaining):
        for b in remaining[i + 1:]:
            if (overlap(words[a["id"]], words[b["id"]]) >= TITLE_OVERLAP
                    and close_in_length(a["word_count"], b["word_count"])):
                candidates.append((a, b))

    if not candidates:
        return []

    wanted = {d["id"] for pair in candidates for d in pair}
    print(f"  comparing the text of {len(wanted)} documents "
          f"across {len(candidates)} candidate pairs…")
    body = texts(wanted)
    fingerprints = {i: shingles(body.get(i, "")) for i in wanted}

    # Pairs that really are the same work, joined into groups.
    parent = {i: i for i in wanted}

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    matched = 0
    for a, b in candidates:
        if overlap(fingerprints[a["id"]], fingerprints[b["id"]]) >= TEXT_OVERLAP:
            parent[root(a["id"])] = root(b["id"])
            matched += 1

    print(f"  {matched} of those pairs share their text; "
          f"the rest only shared a title")

    by_root = defaultdict(list)
    for d in remaining:
        if d["id"] in parent:
            by_root[root(d["id"])].append(d)
    return [g for g in by_root.values() if len(g) > 1]


def show(groups, heading):
    if not groups:
        print(f"\n  {heading}: none found")
        return 0

    print(f"\n  {heading}: {len(groups)} works")
    losers = 0
    for group in groups:
        keep = best_of(group)
        print(f"\n    KEEP  {keep['word_count'] or 0:>7} words  "
              f"{(keep['title'] or keep['filename'])[:58]}")
        print(f"          {keep['filename'][:66]}")
        for d in group:
            if d["id"] == keep["id"]:
                continue
            losers += 1
            print(f"    drop  {d['word_count'] or 0:>7} words  "
                  f"{(d['title'] or d['filename'])[:58]}")
            print(f"          {d['filename'][:66]}")
    return losers


def apply(groups):
    """Mark the copies not kept, and remove their passages."""
    marked = passages = 0
    with db.connect() as conn:
        for group in groups:
            keep = best_of(group)
            label = (keep["title"] or keep["filename"])[:120]
            for d in group:
                if d["id"] == keep["id"]:
                    continue
                gone = conn.execute(
                    "DELETE FROM chunks WHERE doc_id = %s RETURNING id",
                    (d["id"],),
                ).fetchall()
                conn.execute(
                    """
                    UPDATE documents
                       SET status = 'duplicate',
                           status_note = %s
                     WHERE id = %s
                    """,
                    (f"[dup] same work as #{keep['id']} — {label}", d["id"]),
                )
                passages += len(gone)
                marked += 1
        conn.commit()
    return marked, passages


def main():
    docs = load()
    print(f"\n  {len(docs)} documents in the collection")

    identical = group_by_text(docs)
    already = {d["id"] for g in identical for d in g}
    same_work = group_by_work(docs, already)

    held = [g for g in identical + same_work if held_back(g)]
    identical = [g for g in identical if not held_back(g)]
    same_work = [g for g in same_work if not held_back(g)]

    if held:
        print(f"\n  Held back: {len(held)} works")
        for group in held:
            print(f"\n    matched \"{held_back(group)}\" — left alone")
            for d in group:
                print(f"          {d['filename'][:66]}")

    a = show(identical, "Identical extracted text")
    b = show(same_work, "Same work, different copy")

    groups = identical + same_work
    print(f"\n  {a + b} copies would be removed from search, "
          f"leaving {len(docs) - (a + b)} distinct works")

    if not groups:
        return

    if not APPLY:
        print("\n  Nothing has been changed. To carry it out:")
        print("      python dedupe.py --apply")
        print("\n  Read the list first. Two copies that differ in "
              "substance — a 2023 schedule of rates and its 2024 "
              "revision — will look alike here, and only you know "
              "which of those matters.")
        return

    marked, passages = apply(groups)
    print(f"\n  {marked} documents marked as duplicates")
    print(f"  {passages} passages removed")
    print("\n  Their rows are still there, each noting which copy was "
          "kept, so this can be read back or undone.")
    print("  Run  python check.py  to see the space returned.")


if __name__ == "__main__":
    main()
