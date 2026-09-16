"""
What is actually in the Drive.

Counts every file, of every type, in every subfolder — not just the
ones the pipeline can read. Run it once and you have real numbers
rather than estimates:

    python inventory.py

It writes inventory.csv alongside the summary, so the full list can
be opened in a spreadsheet.
"""

import csv
import time
from collections import Counter, defaultdict
from pathlib import Path

import drive
from config import DRIVE_FOLDER_ID

FOLDER = "application/vnd.google-apps.folder"

# tidy names for the mime types that actually turn up
FRIENDLY = {
    "application/pdf": "PDF",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word (.docx)",
    "application/msword": "Word (.doc)",
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel (.xlsx)",
    "application/vnd.ms-excel": "Excel (.xls)",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint (.pptx)",
    "application/vnd.ms-powerpoint": "PowerPoint (.ppt)",
    "image/jpeg": "Image (jpg)",
    "image/png": "Image (png)",
    "image/gif": "Image (gif)",
    "image/heic": "Image (heic)",
    "image/webp": "Image (webp)",
    "video/mp4": "Video (mp4)",
    "video/quicktime": "Video (mov)",
    "audio/mpeg": "Audio (mp3)",
    "application/zip": "Archive (zip)",
    "text/plain": "Text",
    "text/csv": "CSV",
    "application/vnd.google-apps.form": "Google Form",
    "application/vnd.google-apps.shortcut": "Shortcut",
}

# what the pipeline can currently read
READABLE = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/vnd.google-apps.document",
}


def name_for(mime):
    return FRIENDLY.get(mime, mime)


def walk_everything(folder_id, verbose=True):
    """Every file, every type, every subfolder."""
    files = []
    queue = [(folder_id, "")]
    folders = 0
    unreadable = []

    while queue:
        current, prefix = queue.pop(0)
        folders += 1
        page = None

        while True:
            try:
                result = drive.service().files().list(
                    q=f"'{current}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType, size, "
                           "modifiedTime)",
                    pageSize=1000,
                    pageToken=page,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
            except Exception as e:
                unreadable.append((prefix or "(root)", type(e).__name__))
                break

            for f in result.get("files", []):
                if f["mimeType"] == FOLDER:
                    queue.append((f["id"], f"{prefix}{f['name']}/"))
                else:
                    files.append({
                        "folder": prefix or "(root)",
                        "name": f["name"],
                        "type": name_for(f["mimeType"]),
                        "mime": f["mimeType"],
                        "bytes": int(f.get("size", 0)),
                        "modified": f.get("modifiedTime", "")[:10],
                        "readable": f["mimeType"] in READABLE,
                    })

            page = result.get("nextPageToken")
            if not page:
                break

        if verbose and folders % 25 == 0:
            print(f"  ...{folders} folders, {len(files)} files",
                  flush=True)

    return files, folders, unreadable


def main():
    print("Walking the whole Drive. This takes a few minutes.\n")
    start = time.time()

    files, folders, unreadable = walk_everything(DRIVE_FOLDER_ID)

    took = int(time.time() - start)
    print(f"\nDone in {took // 60}m {took % 60}s")
    print(f"  {folders} folders")
    print(f"  {len(files)} files\n")

    # ─── by type ───
    by_type = Counter(f["type"] for f in files)
    size_by_type = defaultdict(int)
    for f in files:
        size_by_type[f["type"]] += f["bytes"]

    print("BY TYPE")
    print(f"  {'type':28} {'count':>7} {'size':>12}")
    print("  " + "-" * 49)
    for kind, n in by_type.most_common():
        mb = size_by_type[kind] / 1_000_000
        size = f"{mb:,.0f} MB" if mb >= 1 else "—"
        print(f"  {kind[:28]:28} {n:>7} {size:>12}")

    # ─── what we can read ───
    readable = [f for f in files if f["readable"]]
    print(f"\nREADABLE BY THE PIPELINE")
    print(f"  {len(readable)} of {len(files)} files "
          f"({100 * len(readable) // max(len(files), 1)}%)")

    # ─── by folder ───
    by_folder = Counter(f["folder"] for f in files)
    readable_by_folder = Counter(f["folder"] for f in readable)

    print(f"\nBY FOLDER  (top 20 of {len(by_folder)})")
    print(f"  {'folder':46} {'files':>7} {'readable':>9}")
    print("  " + "-" * 64)
    for folder, n in by_folder.most_common(20):
        print(f"  {folder[:46]:46} {n:>7} {readable_by_folder[folder]:>9}")

    if unreadable:
        print(f"\n{len(unreadable)} folder(s) could not be read:")
        for path, why in unreadable[:10]:
            print(f"  {path}  ({why})")

    # ─── full list to csv ───
    with open("inventory.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["folder", "name", "type", "bytes",
                            "modified", "readable"],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(files)

    print(f"\nFull list written to inventory.csv")


if __name__ == "__main__":
    main()
