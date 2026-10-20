"""Update a known Google Drive file in place from a local file.

Unlike the magnite/neurox uploader (which upserts by filename within a
folder), this targets an exact fileId with files().update — the Apps Script
viewer link that serves the dashboard is pinned to that id, so the id must
never change. Renaming or trashing the Drive file breaks the link; nothing
here can prevent that.

Auth: a Drive service-account JSON (house convention: the DRIVE_SA secret /
~/.config/seedtag/prj-jdpa-*.json). The service account needs Editor access
to the target file or its parent folder.
"""

from __future__ import annotations

from pathlib import Path


def update_file(sa_json_path: str | Path, file_id: str, local_path: str | Path,
                mime: str = "text/html") -> bool:
    """Replace the Drive file's content. Returns True on success.

    A missing service-account file is a skip, not an error — the daily job
    must keep refreshing the GitHub copy even when Drive creds are absent.
    """
    sa_path = Path(sa_json_path)
    if not sa_path.exists():
        print(f"Drive upload skipped — no service-account file at {sa_path}")
        return False

    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds = service_account.Credentials.from_service_account_file(
        str(sa_path),
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    media = MediaFileUpload(str(local_path), mimetype=mime, resumable=False)
    svc.files().update(
        fileId=file_id,
        media_body=media,
        supportsAllDrives=True,
    ).execute()
    print(f"Updated Drive file {file_id} from {local_path} "
          f"(https://drive.google.com/file/d/{file_id}/view)")
    return True
