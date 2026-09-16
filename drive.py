"""
Reading files from Google Drive.

The first version of this walked the entire folder tree before it
processed anything. On a Drive with hundreds of subfolders that took
the best part of an hour, and a single unreadable folder killed the
whole run.

This version:

  - stops as soon as it has enough files, rather than mapping everything
  - skips folders it cannot read, and says which, rather than aborting
  - retries once or twice, because a 500 from Google is usually a blip
  - prefers larger documents, because a collection of 1 KB templates
    makes for a poor demonstration
"""

import io
import time
from collections import deque
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

WANTED = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.google-apps.document": ".docx",
}

GOOGLE_DOC = "application/vnd.google-apps.document"
FOLDER = "application/vnd.google-apps.folder"

# a Google Doc reports no size, so it needs a stand-in for sorting
ASSUMED_DOC_SIZE = 20_000

_service = None
skipped_folders = []


def service(key_file="drive-key.json"):
    global _service
    if _service is None:
        if not Path(key_file).exists():
            raise RuntimeError(
                f"{key_file} not found. It is the service account key "
                "downloaded from Google Cloud."
            )
        creds = service_account.Credentials.from_service_account_file(
            key_file, scopes=SCOPES
        )
        _service = build("drive", "v3", credentials=creds,
                         cache_discovery=False)
    return _service


def _one_page(folder_id, page_token, attempts=3):
    """One request, retried a couple of times before giving up."""
    last = None
    for attempt in range(attempts):
        try:
            return service().files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, "
                       "modifiedTime, size)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def list_files(folder_id, want=None, verbose=True):
    """
    Readable files in the folder and its subfolders.

    want — stop once this many have been found. None means everything.

    Returns [{id, name, mimeType, size, path}, ...]
    """
    skipped_folders.clear()

    found = []
    queue = deque([(folder_id, "")])
    folders_seen = 0

    while queue:
        current, prefix = queue.popleft()
        folders_seen += 1
        page = None

        while True:
            try:
                result = _one_page(current, page)
            except Exception as e:
                skipped_folders.append((prefix or "(root)", type(e).__name__))
                break

            for f in result.get("files", []):
                if f["mimeType"] == FOLDER:
                    queue.append((f["id"], f"{prefix}{f['name']}/"))
                elif f["mimeType"] in WANTED:
                    f["path"] = prefix + f["name"]
                    f["bytes"] = (ASSUMED_DOC_SIZE
                                  if f["mimeType"] == GOOGLE_DOC
                                  else int(f.get("size", 0)))
                    found.append(f)

            page = result.get("nextPageToken")
            if not page:
                break

        if verbose and folders_seen % 25 == 0:
            print(f"  ...{folders_seen} folders, {len(found)} files so far",
                  flush=True)

        # enough to work with, and a margin so sorting has something to pick from
        if want and len(found) >= want * 4:
            break

    if verbose:
        print(f"  searched {folders_seen} folder(s), found {len(found)} file(s)")
        if skipped_folders:
            print(f"  {len(skipped_folders)} folder(s) could not be read:")
            for path, why in skipped_folders[:5]:
                print(f"    {path}  ({why})")

    # largest first — a 1 KB template is not worth a Gemini call
    found.sort(key=lambda f: f["bytes"], reverse=True)

    return found[:want] if want else found


def download(file_id, mime_type, dest_dir="drive_cache"):
    """Fetch one file locally so the reader can open it."""
    drive = service()
    Path(dest_dir).mkdir(exist_ok=True)

    if mime_type == GOOGLE_DOC:
        request = drive.files().export_media(
            fileId=file_id,
            mimeType="application/vnd.openxmlformats-officedocument"
                     ".wordprocessingml.document",
        )
        suffix = ".docx"
    else:
        request = drive.files().get_media(fileId=file_id,
                                          supportsAllDrives=True)
        suffix = WANTED[mime_type]

    path = Path(dest_dir) / f"{file_id}{suffix}"

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    path.write_bytes(buffer.getvalue())
    return path


if __name__ == "__main__":
    import sys
    from config import DRIVE_FOLDER_ID

    want = int(sys.argv[1]) if len(sys.argv) > 1 else 40

    print(f"Looking for {want} document(s)...\n")
    files = list_files(DRIVE_FOLDER_ID, want=want)

    print(f"\nTaking the {len(files)} largest:\n")
    for f in files:
        print(f"  {f['bytes'] // 1024:6} KB  {f['path'][:70]}")
