"""Safe, resilient local media-library indexing and streaming helpers."""

from __future__ import annotations

import base64
import hashlib
import logging
import mimetypes
import shutil
import subprocess
import threading
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.flac import Picture

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
_METADATA_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()


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


def _text_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00")
    return str(value or "").strip()


def _raw_tag(tags: Any, key: str) -> str:
    if not tags:
        return ""
    wanted = key.casefold()
    candidates = (
        key,
        key.upper(),
        key.lower(),
        f"TXXX:{key.upper()}",
        f"----:com.apple.iTunes:{key.upper()}",
    )
    for candidate in candidates:
        try:
            value = tags.get(candidate)
        except Exception:
            value = None
        text = _text_value(value)
        if text:
            return text
    try:
        for name in tags.keys():
            if str(name).casefold().endswith(wanted):
                text = _text_value(tags.get(name))
                if text:
                    return text
    except Exception:
        pass
    return ""


def _embedded_flags(path: Path) -> dict[str, Any]:
    flags: dict[str, Any] = {
        "has_cover": False,
        "has_lyrics": False,
        "playlist_title": "",
        "playlist_owner": "",
        "playlist_url": "",
    }
    try:
        media = MutagenFile(path, easy=False)
        if media is None:
            return flags
        tags = getattr(media, "tags", None)
        pictures = getattr(media, "pictures", None) or []
        if pictures:
            flags["has_cover"] = True
        if tags:
            try:
                flags["has_cover"] = flags["has_cover"] or bool(tags.getall("APIC"))
                flags["has_lyrics"] = bool(tags.getall("USLT"))
            except Exception:
                pass
            flags["has_cover"] = flags["has_cover"] or bool(
                tags.get("covr") or tags.get("metadata_block_picture") or tags.get("coverart")
            )
            flags["has_lyrics"] = flags["has_lyrics"] or bool(
                tags.get("\xa9lyr") or tags.get("LYRICS") or tags.get("lyrics")
            )
            for key in ("playlist_title", "playlist_owner", "playlist_url"):
                flags[key] = _raw_tag(tags, key)
    except Exception as exc:
        LOGGER.debug("Could not inspect embedded features in %s: %s", path, exc)
    return flags


def read_media_metadata(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {}
    signature = (stat.st_mtime_ns, stat.st_size)
    cache_key = str(path)
    with _CACHE_LOCK:
        cached = _METADATA_CACHE.get(cache_key)
        if cached and cached[0] == signature:
            return dict(cached[1])

    result: dict[str, Any] = {}
    try:
        audio = MutagenFile(path, easy=True)
        if audio is not None:
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
    result.update(_embedded_flags(path))
    result = {key: value for key, value in result.items() if value not in ("", None)}
    with _CACHE_LOCK:
        _METADATA_CACHE[cache_key] = (signature, dict(result))
    return result


def clear_library_cache(root: str | Path | None = None) -> None:
    with _CACHE_LOCK:
        if root is None:
            _METADATA_CACHE.clear()
            return
        base = Path(root).expanduser().resolve()
        for key in [item for item in _METADATA_CACHE if Path(item).is_relative_to(base)]:
            _METADATA_CACHE.pop(key, None)


def read_embedded_cover(path: Path) -> tuple[bytes, str] | None:
    """Return the embedded front cover without exposing the filesystem path."""

    try:
        media = MutagenFile(path, easy=False)
        if media is None:
            return None
        pictures = getattr(media, "pictures", None) or []
        if pictures:
            picture = next((item for item in pictures if getattr(item, "type", 0) == 3), pictures[0])
            return bytes(picture.data), str(picture.mime or "image/jpeg")
        tags = getattr(media, "tags", None)
        if not tags:
            return None
        try:
            frames = tags.getall("APIC")
        except Exception:
            frames = []
        if frames:
            frame = next((item for item in frames if getattr(item, "type", 0) == 3), frames[0])
            return bytes(frame.data), str(frame.mime or "image/jpeg")
        covers = tags.get("covr")
        if covers:
            data = bytes(covers[0])
            return data, "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
        encoded = tags.get("metadata_block_picture")
        if encoded:
            raw = base64.b64decode(_text_value(encoded))
            picture = Picture(raw)
            return bytes(picture.data), str(picture.mime or "image/jpeg")
        legacy = tags.get("coverart")
        if legacy:
            data = base64.b64decode(_text_value(legacy))
            return data, "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
    except Exception as exc:
        LOGGER.debug("Could not read cover from %s: %s", path, exc)
    return None


@lru_cache(maxsize=64)
def _video_poster(path_value: str, modified_ns: int, size: int) -> tuple[bytes, str] | None:
    del modified_ns, size
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "1",
                "-i",
                path_value,
                "-frames:v",
                "1",
                "-vf",
                "scale=720:-2",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if not completed.stdout or len(completed.stdout) > 10 * 1024 * 1024:
        return None
    return completed.stdout, "image/jpeg"


def read_media_artwork(path: Path) -> tuple[bytes, str] | None:
    embedded = read_embedded_cover(path)
    if embedded:
        return embedded
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return _video_poster(str(path), stat.st_mtime_ns, stat.st_size)


def read_embedded_lyrics(path: Path) -> str:
    try:
        media = MutagenFile(path, easy=False)
        if media is None or not media.tags:
            return ""
        tags = media.tags
        try:
            frames = tags.getall("USLT")
        except Exception:
            frames = []
        if frames:
            return str(frames[0].text or "").strip()
        for key in ("\xa9lyr", "LYRICS", "lyrics"):
            text = _text_value(tags.get(key))
            if text:
                return text
    except Exception as exc:
        LOGGER.debug("Could not read lyrics from %s: %s", path, exc)
    return ""


def _track_sort(value: Any) -> int:
    try:
        return int(str(value or "0").split("/", 1)[0])
    except ValueError:
        return 0


def scan_library(
    root: str | Path,
    *,
    limit: int = 250,
    query: str = "",
) -> list[dict[str, Any]]:
    base = Path(root).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        return []
    safe_limit = max(1, min(int(limit or 250), 2000))
    needle = query.casefold().strip()

    candidates: list[tuple[int, Path]] = []
    try:
        iterator = base.rglob("*")
        for path in iterator:
            try:
                resolved = path.resolve()
                resolved.relative_to(base)
                if resolved.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                    candidates.append((path.stat().st_mtime_ns, path))
            except (OSError, ValueError):
                continue
    except OSError as exc:
        LOGGER.warning("Could not scan library root %s: %s", base, exc)
        return []
    candidates.sort(key=lambda item: item[0], reverse=True)

    items: list[dict[str, Any]] = []
    active_paths: set[str] = set()
    for _, path in candidates:
        try:
            relative = path.relative_to(base)
            stat = path.stat()
        except (OSError, ValueError):
            continue
        active_paths.add(str(path))
        media_id = encode_media_id(relative)
        metadata = read_media_metadata(path)
        if len(relative.parts) >= 3 and relative.parts[0].casefold() == "playlists":
            metadata.setdefault("playlist_title", relative.parts[1])
        is_video = path.suffix.lower() in VIDEO_EXTENSIONS
        has_artwork = bool(metadata.get("has_cover")) or is_video
        item = {
            "id": media_id,
            "name": path.name,
            "relative_path": relative.as_posix(),
            "kind": "video" if is_video else "audio",
            "format": path.suffix.lower().lstrip("."),
            "size": stat.st_size,
            "modified_at": int(stat.st_mtime),
            "stream_url": f"/api/library/media/{media_id}",
            "artwork_url": f"/api/library/artwork/{media_id}" if has_artwork else "",
            "has_artwork": has_artwork,
            "lyrics_url": f"/api/library/lyrics/{media_id}" if metadata.get("has_lyrics") else "",
            "title": metadata.pop("title", path.stem),
            "artist": metadata.pop("artist", ""),
            "album": metadata.pop("album", ""),
            **metadata,
        }
        if needle and needle not in " ".join(
            str(item.get(key) or "")
            for key in ("title", "artist", "album", "album_artist", "playlist_title", "name", "relative_path")
        ).casefold():
            continue
        items.append(item)
        if len(items) >= safe_limit:
            break

    with _CACHE_LOCK:
        for key in [entry for entry in _METADATA_CACHE if Path(entry).is_relative_to(base) and entry not in active_paths]:
            _METADATA_CACHE.pop(key, None)
    return items


def _group_id(kind: str, *parts: str) -> str:
    value = "\x1f".join([kind, *[str(part or "").casefold() for part in parts]])
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def build_library_catalog(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Create stable artist/album/playlist facets from a fresh scan."""

    artists: dict[str, dict[str, Any]] = {}
    albums: dict[tuple[str, str], dict[str, Any]] = {}
    playlists: dict[str, dict[str, Any]] = {}
    artist_album_ids: dict[str, set[str]] = defaultdict(set)

    def cover_of(item: dict[str, Any]) -> str:
        return str(item.get("artwork_url") or "")

    for item in items:
        artist_name = str(item.get("album_artist") or item.get("artist") or "Artista desconocido")
        album_name = str(item.get("album") or "Sin álbum")
        artist_key = artist_name.casefold()
        artist = artists.setdefault(
            artist_key,
            {
                "id": _group_id("artist", artist_name),
                "name": artist_name,
                "item_ids": [],
                "album_ids": [],
                "cover_url": "",
                "duration": 0,
            },
        )
        artist["item_ids"].append(item["id"])
        artist["duration"] += float(item.get("duration") or 0)
        artist["cover_url"] = artist["cover_url"] or cover_of(item)

        album_key = (artist_key, album_name.casefold())
        album = albums.setdefault(
            album_key,
            {
                "id": _group_id("album", artist_name, album_name),
                "title": album_name,
                "artist": artist_name,
                "year": str(item.get("date") or "")[:4],
                "item_ids": [],
                "cover_url": "",
                "duration": 0,
            },
        )
        album["item_ids"].append(item["id"])
        album["duration"] += float(item.get("duration") or 0)
        album["cover_url"] = album["cover_url"] or cover_of(item)
        artist_album_ids[artist_key].add(album["id"])

        playlist_name = str(item.get("playlist_title") or "").strip()
        if playlist_name:
            playlist_key = playlist_name.casefold()
            playlist = playlists.setdefault(
                playlist_key,
                {
                    "id": _group_id("playlist", playlist_name),
                    "title": playlist_name,
                    "owner": str(item.get("playlist_owner") or ""),
                    "item_ids": [],
                    "cover_url": "",
                    "duration": 0,
                },
            )
            playlist["item_ids"].append(item["id"])
            playlist["duration"] += float(item.get("duration") or 0)
            playlist["cover_url"] = playlist["cover_url"] or cover_of(item)

    item_by_id = {item["id"]: item for item in items}
    for collection in artists.values():
        collection["item_ids"].sort(
            key=lambda media_id: (
                str(item_by_id[media_id].get("date") or ""),
                str(item_by_id[media_id].get("album") or "").casefold(),
                _track_sort(item_by_id[media_id].get("disc")),
                _track_sort(item_by_id[media_id].get("track")),
                str(item_by_id[media_id].get("title") or "").casefold(),
            )
        )
    for collection in albums.values():
        collection["item_ids"].sort(
            key=lambda media_id: (
                _track_sort(item_by_id[media_id].get("disc")),
                _track_sort(item_by_id[media_id].get("track")),
                str(item_by_id[media_id].get("title") or "").casefold(),
            )
        )
    for collection in playlists.values():
        collection["item_ids"].sort(
            key=lambda media_id: (
                _track_sort(item_by_id[media_id].get("playlist_position")),
                _track_sort(item_by_id[media_id].get("track")),
                str(item_by_id[media_id].get("title") or "").casefold(),
            )
        )
    for collection in (*artists.values(), *albums.values(), *playlists.values()):
        collection["count"] = len(collection["item_ids"])
        collection["duration"] = round(collection["duration"], 2)
    for key, artist in artists.items():
        artist["album_ids"] = sorted(artist_album_ids[key])
        artist["album_count"] = len(artist["album_ids"])

    return {
        "summary": {
            "items": len(items),
            "artists": len(artists),
            "albums": len(albums),
            "playlists": len(playlists),
            "songs": sum(item.get("kind") == "audio" for item in items),
            "videos": sum(item.get("kind") == "video" for item in items),
            "with_cover": sum(bool(item.get("has_cover")) for item in items),
            "with_lyrics": sum(bool(item.get("has_lyrics")) for item in items),
        },
        "artists": sorted(artists.values(), key=lambda item: item["name"].casefold()),
        "albums": sorted(albums.values(), key=lambda item: (item["artist"].casefold(), item["title"].casefold())),
        "playlists": sorted(playlists.values(), key=lambda item: item["title"].casefold()),
    }


def media_mimetype(path: Path) -> str:
    overrides = {
        ".m4a": "audio/mp4",
        ".mkv": "video/x-matroska",
        ".opus": "audio/ogg",
    }
    return overrides.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
