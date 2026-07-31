"""Safe local media-library indexing and streaming helpers."""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile

LOGGER = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".mp4",
    ".mkv",
    ".webm",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".wav",
    ".aac",
}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm"}


def encode_media_id(relative_path: str | Path) -> str:
    value = Path(relative_path).as_posix().encode("utf-8")
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_media_id(media_id: str) -> Path:
    if not media_id or len(media_id) > 4096:
        raise ValueError("Identificador de medio invalido")
    padding = "=" * (-len(media_id) % 4)
    try:
        decoded = base64.urlsafe_b64decode(media_id + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Identificador de medio invalido") from exc
    relative = Path(decoded)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Ruta de medio insegura")
    return relative


def resolve_media_path(root: str | Path, media_id: str) -> Path:
    base = Path(root).expanduser().resolve()
    candidate = (base / decode_media_id(media_id)).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError("Ruta fuera de la biblioteca") from exc
    if not candidate.is_file() or candidate.suffix.lower() not in MEDIA_EXTENSIONS:
        raise FileNotFoundError("Archivo multimedia no encontrado")
    return candidate


def _first(tags: Any, *keys: str) -> str:
    for key in keys:
        try:
            value = tags.get(key)
        except Exception:
            continue
        if isinstance(value, (list, tuple)) and value:
            value = value[0]
        if value not in (None, ""):
            return str(value)
    return ""


def read_media_metadata(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return result
        tags = audio.tags or {}
        result.update(
            {
                "title": _first(tags, "title"),
                "artist": _first(tags, "artist"),
                "album": _first(tags, "album"),
                "album_artist": _first(tags, "albumartist"),
                "genre": _first(tags, "genre"),
                "date": _first(tags, "date", "year"),
                "track": _first(tags, "tracknumber"),
                "disc": _first(tags, "discnumber"),
            }
        )
        info = getattr(audio, "info", None)
        if info and getattr(info, "length", None):
            result["duration"] = round(float(info.length), 2)
        if info and getattr(info, "bitrate", None):
            result["bitrate"] = int(info.bitrate)
    except Exception as exc:
        LOGGER.debug("Could not read tags from %s: %s", path, exc)
    return {key: value for key, value in result.items() if value not in ("", None)}


def scan_library(
    root: str | Path,
    *,
    limit: int = 250,
    query: str = "",
) -> list[dict[str, Any]]:
    base = Path(root).expanduser().resolve()
    if not base.exists():
        return []
    safe_limit = max(1, min(int(limit or 250), 1000))
    needle = query.casefold().strip()

    candidates: list[Path] = []
    for path in base.rglob("*"):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            if needle and needle not in path.name.casefold() and needle not in str(path.parent).casefold():
                continue
            candidates.append(path)
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)

    items: list[dict[str, Any]] = []
    for path in candidates[:safe_limit]:
        relative = path.relative_to(base)
        media_id = encode_media_id(relative)
        metadata = read_media_metadata(path)
        stat = path.stat()
        items.append(
            {
                "id": media_id,
                "name": path.name,
                "relative_path": relative.as_posix(),
                "kind": "video" if path.suffix.lower() in VIDEO_EXTENSIONS else "audio",
                "format": path.suffix.lower().lstrip("."),
                "size": stat.st_size,
                "modified_at": int(stat.st_mtime),
                "stream_url": f"/api/library/media/{media_id}",
                "title": metadata.pop("title", path.stem),
                "artist": metadata.pop("artist", ""),
                "album": metadata.pop("album", ""),
                **metadata,
            }
        )
    return items


def media_mimetype(path: Path) -> str:
    overrides = {
        ".m4a": "audio/mp4",
        ".mkv": "video/x-matroska",
        ".opus": "audio/ogg",
    }
    return overrides.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"

