"""
Reading documents into the system.

Run it with:      python ingest.py
Or on a folder:   python ingest.py path\\to\\folder

Safe to stop and re-run. Documents already processed are skipped,
so a run interrupted by a rate limit or a network drop picks up
where it left off rather than starting again.
"""

import sys
import time
from pathlib import Path

import db
from config import DOCS_DIR, MIN_WORDS_PER_DOC
import reader
import chunker
import labeller
import embedder

SUPPORTED = {".pdf", ".docx", ".doc"}


def ingest_file(path):
    """Returns a short status string for the console."""
    path = Path(path)
    h = reader.file_hash(path)

    if db.already_ingested(h):
        return "skipped (already done)"

    pages, note = reader.read(path)
    if note:
        db.record_excluded(path.name, h, str(path), note)
        return f"excluded ({note})"

    full_text = "\n\n".join(t for _, t in pages)
    words = len(full_text.split())

    if words < MIN_WORDS_PER_DOC:
        reason = f"too little text ({words} words)"
        db.record_excluded(path.name, h, str(path), reason)
        return f"excluded ({reason})"

    chunks = chunker.split_document(pages)
    if not chunks:
        db.record_excluded(path.name, h, str(path), "no usable passages")
        return "excluded (no usable passages)"

    meta = labeller.label(full_text)
    vectors = embedder.embed_many([c["text"] for c in chunks],
                                  show_progress=False)

    doc_id = db.insert_document(
        filename=path.name,
        content_hash=h,
        source_path=str(path),
        page_count=len(pages),
        word_count=words,
        full_text=full_text,
        meta=meta,
    )
    db.insert_chunks(doc_id, chunks, vectors)

    return f"ok — {len(pages)} pages, {len(chunks)} passages"


def main(folder=None):
    folder = Path(folder or DOCS_DIR)
    if not folder.exists():
        print(f"Folder not found: {folder.resolve()}")
        print("Create it and put some documents in, or pass a path:")
        print("    python ingest.py path\\to\\folder")
        return

    files = sorted(
        p for p in folder.rglob("*")
        if p.suffix.lower() in SUPPORTED and not p.name.startswith("~$")
    )

    if not files:
        print(f"No PDF or Word files found in {folder.resolve()}")
        return

    print(f"Found {len(files)} file(s) in {folder.resolve()}\n")

    counts = {"ok": 0, "skipped": 0, "excluded": 0, "failed": 0}

    for i, path in enumerate(files, start=1):
        label = path.name[:52]
        print(f"[{i}/{len(files)}] {label:54}", end=" ", flush=True)
        try:
            result = ingest_file(path)
            print(result)
            if result.startswith("ok"):
                counts["ok"] += 1
            elif result.startswith("skipped"):
                counts["skipped"] += 1
            else:
                counts["excluded"] += 1
        except Exception as e:
            print(f"FAILED — {type(e).__name__}: {e}")
            counts["failed"] += 1

        time.sleep(1)      # gentle on the free tier

    print("\n" + "-" * 68)
    print(f"  added     {counts['ok']}")
    print(f"  skipped   {counts['skipped']}")
    print(f"  excluded  {counts['excluded']}")
    print(f"  failed    {counts['failed']}")

    by_status, n_chunks = db.counts()
    print(f"\n  collection now: {by_status}, {n_chunks} passages")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
