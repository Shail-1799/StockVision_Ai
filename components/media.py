"""Turns a stored local file path into the /media/<filename> URL served by
app.py's Flask route, for showing an uploaded/processed image in the UI."""
from pathlib import Path


def media_url(path: str) -> str | None:
    if not path:
        return None
    return f"/media/{Path(path).name}"
