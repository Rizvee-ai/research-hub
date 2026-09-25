"""
Cutting the collection into passages again, at whatever size config.py
now says, without re-reading a single file.

    python rechunk.py            show what would change, change nothing
    python rechunk.py --apply    carry it out

Why this is cheap. Ingestion has six steps and only the last three run
here: downloading from Drive, reading and transcribing scanned pages,
and labelling with Gemini all happened once and their results are kept.
What repeats is cutting text into passages and turning those into
vectors, and vectors are computed on this machine — no API, no cost, no
rate limit.

Where the text comes from. Not from full_text: that is the pages joined
together, with empty pages dropped, so page numbers cannot be recovered
from it — and a passage without a page number cannot carry a citation.
The pages are rebuilt from the existing passages instead, which each
carry the page they came from.

Rebuilding a page means undoing the overlap. Passages were cut at a
fixed stride, so each one after the first repeats the last CHUNK_OVERLAP
words of the one before it. Dropping those repeated words and joining
what is left returns the page exactly. Every document is then checked
against its own stored full_text before anything is replaced; a document
that does not reconstruct cleanly is skipped and named, rather than
being quietly rebuilt from text that might be wrong.

It also gives each passage its document's context before embedding it.
The measurement showed why. Questions that named an organisation —
"what qualifications do the instructors at Frontline Mind have" — failed
to reach even the top fifty, because the passage answering them is a
list of biographies that never says "Frontline Mind". The brochure says
that on its cover, not in every paragraph. Prefixing the title and the
first line of the summary before embedding gives every passage the
context a reader would have had. The stored text is untouched, so
citations and the passages shown in the interface are unaffected — only
the vector changes.

Before running this, change CHUNK_WORDS and CHUNK_OVERLAP in config.py.
This reads the new values from there, so the collection and the settings
that future ingestion will use cannot drift apart.
"""

import re
import sys
from pathlib import Path

import chunker
import db
import embedder
from config import CHUNK_WORDS, CHUNK_OVERLAP

APPLY = "--apply" in sys.argv

# The settings the existing passages were cut with. If you have changed
# config.py more than once without re-chunking, set these to whatever
# was in force when the passages in the database were made, or the
# pages will not rebuild.
WAS_WORDS = 600
WAS_OVERLAP = 90

# Put the document's title and a line of its summary in front of each
# passage before embedding it. The passage stored and shown stays as it
# is; only what the vector is computed from changes.
WITH_CONTEXT = True


def words_of(text):
    return (text or "").split()


def context_for(doc):
    """
    The line put in front of a passage before it is embedded.

    Title plus the first sentence of the summary. Enough to say what
    document this is, short enough not to drown the passage itself.
    """
    if not WITH_CONTEXT:
        return ""
    bits = []
    if doc["title"]:
        bits.append(doc["title"].strip())
    summary = (doc["summary"] or "").strip()
    if summary:
        first = re.split(r"(?<=[.!?])\s", summary)[0]
        if len(first) > 30:
            bits.append(first)
    return " — ".join(bits) + "\n\n" if bits else ""


def rebuild_page(passages, overlap=WAS_OVERLAP):
    """
    One page's text, from its passages, with the repetition removed.

    passages is the list of texts in seq order. The first is kept whole;
    every one after it begins with `overlap` words already seen, so only
    what follows them is new.
    """
    if not passages:
        return []
    out = words_of(passages[0])
    for piece in passages[1:]:
        w = words_of(piece)
        out.extend(w[overlap:] if len(w) > overlap else [])
    return out


def shared_words(a, b):
    """How many words the end of a and the start of b have in common."""
    aw, bw = words_of(a), words_of(b)
    limit = min(len(aw), len(bw), max(WAS_OVERLAP, CHUNK_OVERLAP) + 5)
    for k in range(limit, 0, -1):
        if aw[-k:] == bw[:k]:
            return k
    return 0


def already_converted(doc_id, conn):
    """
    Has this document already been cut at the new size?

    A run interrupted part way leaves some converted and some not.
    Rebuilding a converted one would strip WAS_OVERLAP words from
    passages that overlap by only CHUNK_OVERLAP, quietly losing text,
    and the result would still look like a document merely missing its
    title page — so the check would wave it through.

    Measured from the passages themselves: two passages of one page
    share exactly the overlap they were cut with. Asking instead whether
    the longest passage is under the new size was wrong, because a short
    document has short passages whatever size it was cut at, and it
    wrongly claimed two hundred flyers and forms were already done.

    A document with no page holding two passages cannot be judged this
    way, and is treated as not converted. Re-cutting it is harmless —
    a page shorter than the passage size stays one passage — and it
    still gains the title prefix, which those short documents need most.
    """
    rows = conn.execute(
        "SELECT page, seq, text FROM chunks WHERE doc_id = %s ORDER BY seq",
        (doc_id,),
    ).fetchall()

    for a, b in zip(rows, rows[1:]):
        if a["page"] == b["page"]:
            return shared_words(a["text"], b["text"]) == CHUNK_OVERLAP
    return False


def pages_of(doc_id, conn):
    """Every page of a document, rebuilt, in order."""
    rows = conn.execute(
        "SELECT page, seq, text FROM chunks WHERE doc_id = %s ORDER BY seq",
        (doc_id,),
    ).fetchall()

    pages, current, page_no = [], [], None
    for r in rows:
        if r["page"] != page_no:
            if current:
                pages.append((page_no, " ".join(rebuild_page(current))))
            current, page_no = [], r["page"]
        current.append(r["text"])
    if current:
        pages.append((page_no, " ".join(rebuild_page(current))))
    return pages


def divergence(pages, full_text):
    """
    Where the rebuilt text and the stored text first differ, and by how
    much. Printed for the documents that fail, so a skip is a finding
    rather than a shrug.
    """
    rebuilt = " ".join(t for _, t in pages).split()
    stored = (full_text or "").split()

    at = None
    for i in range(min(len(rebuilt), len(stored))):
        if rebuilt[i] != stored[i]:
            at = i
            break
    if at is None and len(rebuilt) != len(stored):
        at = min(len(rebuilt), len(stored))

    return {
        "rebuilt": len(rebuilt),
        "stored": len(stored),
        "at": at,
        "rebuilt_here": " ".join(rebuilt[at:at + 12]) if at is not None else "",
        "stored_here": " ".join(stored[at:at + 12]) if at is not None else "",
    }


def compare(pages, full_text):
    """
    How the rebuilt text stands against the stored full text.

      "exact"     the same words, in the same order
      "partial"   every rebuilt word appears in the stored text in the
                  same order, but some stored words are missing
      "mismatch"  something else

    "partial" is common and is not a fault in this script. Documents
    ingested before the reader was rewritten had any page under
    twenty-five words dropped before chunking, while the full text kept
    it — so their title pages are in the database but were never turned
    into passages. Re-cutting what passages do exist loses nothing,
    because those words are not searchable now either. They are worth
    recovering by ingesting those files again, which is a separate job.

    "mismatch" means words appear that are not in the stored text, in an
    order the stored text does not have. That would be a fault here, and
    those documents are left alone.
    """
    rebuilt = " ".join(t for _, t in pages).split()
    stored = (full_text or "").split()

    if rebuilt == stored:
        return "exact", 0

    # Is every rebuilt word present in the stored text, in order?
    i = 0
    for word in stored:
        if i < len(rebuilt) and rebuilt[i] == word:
            i += 1
    if i == len(rebuilt):
        return "partial", len(stored) - len(rebuilt)

    return "mismatch", len(stored) - len(rebuilt)


def documents(conn):
    return conn.execute(
        """
        SELECT d.id, d.filename, d.title, d.summary, d.full_text,
               count(c.id) AS passages
        FROM documents d JOIN chunks c ON c.doc_id = d.id
        WHERE d.status = 'ingested'
        GROUP BY d.id ORDER BY d.id
        """
    ).fetchall()


def main():
    if (CHUNK_WORDS, CHUNK_OVERLAP) == (WAS_WORDS, WAS_OVERLAP):
        print(f"\n  config.py still says {CHUNK_WORDS} words, "
              f"{CHUNK_OVERLAP} overlap — the same as the passages already "
              f"in the database.")
        print("  Change those two values in config.py first; this brings "
              "the collection into line with them.\n")
        return

    print(f"\n  passages in the database   {WAS_WORDS} words, "
          f"{WAS_OVERLAP} overlap")
    print(f"  config.py now says         {CHUNK_WORDS} words, "
          f"{CHUNK_OVERLAP} overlap\n")

    with db.connect() as conn:
        docs = documents(conn)

        checked = skipped = done_already = before = after = 0
        bad = []
        incomplete = []
        plan = []

        for i, d in enumerate(docs, start=1):
            if already_converted(d["id"], conn):
                done_already += 1
                before += d["passages"]
                after += d["passages"]
                continue

            pages = pages_of(d["id"], conn)
            verdict, missing = compare(pages, d["full_text"])

            if verdict == "mismatch":
                skipped += 1
                bad.append(((d["title"] or d["filename"]),
                            divergence(pages, d["full_text"])))
                continue

            if verdict == "partial":
                incomplete.append((d["filename"],
                                   d["title"] or d["filename"], missing))

            new = chunker.split_document(pages)
            checked += 1
            before += d["passages"]
            after += len(new)
            plan.append((d, pages, len(new)))

            if i % 50 == 0:
                print(f"  ...checked {i} of {len(docs)}")

    if done_already:
        print(f"\n  already at the new size          {done_already}"
              f"   — left alone, from an earlier run")

    print(f"\n  documents that rebuild           {checked}")
    print(f"  of those, complete               {checked - len(incomplete)}")
    print(f"  of those, missing some text      {len(incomplete)}")
    print(f"  documents skipped                {skipped}")

    if incomplete:
        total_missing = sum(m for _, _, m in incomplete)
        print(f"\n      {len(incomplete)} documents hold text that has no "
              f"passages — {total_missing} words in all.")
        print(f"      They were read before the reader was rewritten, when "
              f"pages under")
        print(f"      twenty-five words were dropped before chunking. Their "
              f"title pages")
        print(f"      are in the database and have never been searchable.")
        print(f"\n      Re-cutting them loses nothing: those words are not "
              f"searchable now")
        print(f"      either. Ingesting those files again would recover "
              f"them. The list is")
        print(f"      written to reingest.txt.\n")
        for _, name, missing in sorted(incomplete, key=lambda x: -x[2])[:5]:
            print(f"        {missing:6} words   {name[:56]}")
        if len(incomplete) > 5:
            print(f"        ...and {len(incomplete) - 5} more")

        Path("reingest.txt").write_text(
            "\n".join(f"{m:8}  {f}" for f, _, m in
                      sorted(incomplete, key=lambda x: -x[2])),
            encoding="utf-8")

    if bad:
        shorter = sum(1 for _, d in bad if d["rebuilt"] < d["stored"])
        longer = sum(1 for _, d in bad if d["rebuilt"] > d["stored"])
        same = len(bad) - shorter - longer
        print(f"\n      rebuilt text shorter than stored   {shorter}")
        print(f"      rebuilt text longer than stored    {longer}")
        print(f"      same length, different words       {same}")

        print(f"\n      the first few, and where they diverge:\n")
        for name, d in bad[:5]:
            print(f"      {name[:64]}")
            print(f"        rebuilt {d['rebuilt']} words, "
                  f"stored {d['stored']}, first differ at word {d['at']}")
            print(f"        rebuilt: ...{d['rebuilt_here'][:70]}")
            print(f"        stored : ...{d['stored_here'][:70]}\n")
        if len(bad) > 5:
            print(f"      ...and {len(bad) - 5} more")

    print(f"\n  passages now                     {before}")
    print(f"  passages after                   {after}"
          f"   ({after / max(before, 1):.1f}x)")
    if WITH_CONTEXT:
        print(f"\n  Each passage will be embedded with its document's title "
              f"in front of it.\n  For example:\n")
        for d, _, _ in plan[:2]:
            line = context_for(d).strip().replace("\n", " ")
            if line:
                print(f"      {line[:96]}")
        print(f"\n  The stored passage is unchanged — this only affects "
              f"what the vector\n  is computed from, not what is shown or "
              f"cited.")

    print(f"\n  Nothing else changes. No file is downloaded, no page is "
          f"transcribed again,\n  no document is relabelled, and no Gemini "
          f"call is made. Vectors are\n  computed on this machine.")

    if not APPLY:
        print("\n  Nothing has been changed. To carry it out:")
        print("      python rechunk.py --apply")
        print("\n  Afterwards, run:  python run_cases.py c1")
        print("  If retrieval accuracy has not improved, put CHUNK_WORDS "
              "back,\n  set WAS_WORDS at the top of this file to the size "
              "you just used,\n  and run it again. Nothing is lost either "
              "way.\n")
        return

    print(f"\n  Re-embedding {after} passages. This is the slow part, "
          f"and it is local.\n")

    done = 0
    with db.connect() as conn:
        for d, pages, _ in plan:
            new = chunker.split_document(pages)
            prefix = context_for(d)
            vectors = embedder.embed_many(
                [prefix + c["text"] for c in new], show_progress=False)
            conn.execute("DELETE FROM chunks WHERE doc_id = %s", (d["id"],))
            with conn.cursor() as cur:
                for ch, vec in zip(new, vectors):
                    cur.execute(
                        "INSERT INTO chunks (doc_id, page, seq, text, "
                        "embedding) VALUES (%s, %s, %s, %s, %s)",
                        (d["id"], ch["page"], ch["seq"], ch["text"],
                         "[" + ",".join(f"{x:.6f}" for x in vec) + "]"),
                    )
            conn.commit()
            done += 1
            if done % 25 == 0:
                print(f"  ...{done} of {len(plan)} documents")

    print(f"\n  {done} documents re-cut into {after} passages.")
    print(f"  {skipped} were skipped and still hold their old passages.")
    print("\n  Now measure it:  python run_cases.py c1\n")


if __name__ == "__main__":
    main()
