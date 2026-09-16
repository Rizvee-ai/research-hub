"""
Reading documents into the system, straight from Google Drive.

    python ingest_drive.py              everything in the folder
    python ingest_drive.py 30           just the first 30

Safe to stop and re-run. Anything already processed is skipped, so a
run interrupted by a rate limit or a dropped connection picks up where
it stopped rather than starting again.
"""

import sys
import time
from pathlib import Path

import db
import drive
import reader
import chunker
import labeller
import embedder
from config import DRIVE_FOLDER_ID, MIN_WORDS_PER_DOC


def ingest_one(item):
    """item is a dict from drive.list_files(). Returns a status string."""
    local = None
    try:
        local = drive.download(item["id"], item["mimeType"])
        h = reader.file_hash(local)

        if db.already_ingested(h):
            return "skipped (already done)"

        pages, note = reader.read(local)
        if note:
            db.record_excluded(item["name"], h, item["path"], note)
            return f"excluded ({note})"

        full_text = "\n\n".join(t for _, t in pages)
        words = len(full_text.split())

        if words < MIN_WORDS_PER_DOC:
            reason = f"too little text ({words} words)"
            db.record_excluded(item["name"], h, item["path"], reason)
            return f"excluded ({reason})"

        chunks = chunker.split_document(pages)
        if not chunks:
            db.record_excluded(item["name"], h, item["path"],
                               "no usable passages")
            return "excluded (no usable passages)"

        meta = labeller.label(full_text)
        vectors = embedder.embed_many([c["text"] for c in chunks],
                                      show_progress=False)

        doc_id = db.insert_document(
            filename=item["name"],
            content_hash=h,
            source_path=f"https://drive.google.com/file/d/{item['id']}/view",
            page_count=len(pages),
            word_count=words,
            full_text=full_text,
            meta=meta,
        )
        db.insert_chunks(doc_id, chunks, vectors)

        return f"ok — {len(pages)} pages, {len(chunks)} passages"

    finally:
        # the local copy was only needed to read it
        if local and Path(local).exists():
            try:
                Path(local).unlink()
            except OSError:
                pass


def main(limit=None, folder_id=None):
    folder_id = folder_id or DRIVE_FOLDER_ID
    if not folder_id:
        print("DRIVE_FOLDER_ID is not set. Add it to your .env file.")
        return

    print("Listing files in Drive...")
    try:
        files = drive.list_files(folder_id, want=limit)
    except Exception as e:
        print(f"Could not read the folder: {e}")
        print("\nCheck that the folder has been shared with the service "
              "account, as Viewer.")
        return

    if not files:
        print("No readable files found. The folder may be empty, or may "
              "hold only formats this cannot read.")
        return

    print(f"Found {len(files)} readable file(s)")

    if limit:
        print(f"Processing the {len(files)} largest\n")
    else:
        print()

    counts = {"ok": 0, "skipped": 0, "excluded": 0, "failed": 0}

    for i, item in enumerate(files, start=1):
        label = item["path"][-52:]
        print(f"[{i}/{len(files)}] {label:54}", end=" ", flush=True)
        try:
            result = ingest_one(item)
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
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(limit)
