"""Recoverable, conservative migration for an existing media library.

The public entry points are :func:`repair_library` and
:func:`rollback_library_repair`.  Planning is always performed before any file
is changed.  Apply mode never overwrites a destination and writes a semantic
tag backup plus an append-safe JSON journal before moving each file.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from mutagen import File as MutagenFile
from mutagen.id3 import ID3, ID3NoHeaderError
from mutagen.mp4 import MP4
from mutagen.wave import WAVE

from .audio_analysis import analyze_loudness
from .enrichment import enrich_with_musicbrainz
from .library import read_embedded_cover, read_embedded_lyrics
from .metadata import ADVANCED_FIELDS, PROVENANCE_FIELDS, write_lyrics, write_metadata

JOURNAL_SCHEMA_VERSION = 1
SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".mp4", ".flac", ".ogg", ".oga", ".opus", ".wav"}
UNKNOWN_VALUES = {
    "",
    "unknown",
    "unknown artist",
    "unknown album",
    "unknown title",
    "artista desconocido",
    "album desconocido",
    "álbum desconocido",
    "sin artista",
    "sin album",
    "sin álbum",
    "n/a",
    "none",
    "null",
}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *{f"COM{index}" for index in range(1, 10)},
    *{f"LPT{index}" for index in range(1, 10)},
}
CUSTOM_FIELDS = {
    *ADVANCED_FIELDS,
    *PROVENANCE_FIELDS,
    "source_url",
    "encoded_by",
    "release_type",
    "release_country",
    "release_status",
    "catalog_number",
    "barcode",
    "mood",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(_json_safe(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _within_root(root: Path, candidate: Path) -> Path:
    resolved = candidate.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Ruta fuera de la biblioteca: {candidate}") from exc
    return resolved


def validate_library_root(root: str | Path) -> Path:
    """Resolve a usable library root and reject filesystem-wide targets."""

    resolved = Path(root).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError(f"La raiz no es una carpeta: {resolved}")
    anchor = Path(resolved.anchor).resolve(strict=False)
    if resolved == anchor:
        raise ValueError("No se permite usar la raiz completa del sistema")
    return resolved


def is_unknown(value: Any) -> bool:
    return str(value or "").strip().casefold() in UNKNOWN_VALUES


def safe_component(value: Any, *, max_length: int = 120) -> str:
    """Return one Windows-safe path component without inventing a value."""

    text = unicodedata.normalize("NFC", str(value or "")).strip()
    text = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", text)
    text = re.sub(r"\s+", " ", text).rstrip(" .")
    if len(text) > max_length:
        text = text[:max_length].rstrip(" .")
    if text.upper() in WINDOWS_RESERVED_NAMES:
        text = f"_{text}"
    return text


def _first_value(tags: Any, *keys: str) -> str:
    for key in keys:
        try:
            value = tags.get(key)
        except Exception:
            continue
        if hasattr(value, "text"):
            value = value.text
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace").strip("\x00")
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _split_fraction(value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    if not text:
        return "", ""
    current, separator, total = text.partition("/")
    return current.strip(), total.strip() if separator else ""


def _read_id3_metadata(path: Path) -> dict[str, Any]:
    try:
        if path.suffix.lower() == ".wav":
            wave = WAVE(path)
            tags = wave.tags
            if tags is None:
                return {}
        else:
            tags = ID3(path)
    except (ID3NoHeaderError, OSError, ValueError):
        return {}

    track, track_total = _split_fraction(_first_value(tags, "TRCK"))
    disc, disc_total = _split_fraction(_first_value(tags, "TPOS"))
    result: dict[str, Any] = {
        "title": _first_value(tags, "TIT2"),
        "artist": _first_value(tags, "TPE1"),
        "album": _first_value(tags, "TALB"),
        "album_artist": _first_value(tags, "TPE2"),
        "year": _first_value(tags, "TDRC"),
        "track": track,
        "track_total": track_total,
        "disc": disc,
        "disc_total": disc_total,
        "genre": _first_value(tags, "TCON"),
        "composer": _first_value(tags, "TCOM"),
        "publisher": _first_value(tags, "TPUB"),
        "copyright": _first_value(tags, "TCOP"),
        "language": _first_value(tags, "TLAN"),
        "bpm": _first_value(tags, "TBPM"),
        "isrc": _first_value(tags, "TSRC"),
        "grouping": _first_value(tags, "TIT1"),
        "encoded_by": _first_value(tags, "TENC"),
    }
    comments = tags.getall("COMM")
    for frame in comments:
        text = str(getattr(frame, "text", [""])[0] or "").strip()
        if not text:
            continue
        if str(getattr(frame, "desc", "")).upper() == "DESCRIPTION":
            result["description"] = text
        elif not result.get("comment"):
            result["comment"] = text
    for frame in tags.getall("TXXX"):
        key = str(getattr(frame, "desc", "")).strip().casefold()
        value = _first_value({key: getattr(frame, "text", [])}, key)
        if key in CUSTOM_FIELDS and value:
            result[key] = value
    return {key: value for key, value in result.items() if value not in (None, "")}


def _read_mp4_metadata(path: Path) -> dict[str, Any]:
    try:
        audio = MP4(path)
    except (OSError, ValueError):
        return {}
    tags = audio.tags or {}
    track_pair = (tags.get("trkn") or [(0, 0)])[0]
    disc_pair = (tags.get("disk") or [(0, 0)])[0]
    result: dict[str, Any] = {
        "title": _first_value(tags, "\xa9nam"),
        "artist": _first_value(tags, "\xa9ART"),
        "album": _first_value(tags, "\xa9alb"),
        "album_artist": _first_value(tags, "aART"),
        "year": _first_value(tags, "\xa9day"),
        "genre": _first_value(tags, "\xa9gen"),
        "composer": _first_value(tags, "\xa9wrt"),
        "copyright": _first_value(tags, "cprt"),
        "comment": _first_value(tags, "\xa9cmt"),
        "grouping": _first_value(tags, "\xa9grp"),
        "encoded_by": _first_value(tags, "\xa9too"),
        "track": str(track_pair[0] or ""),
        "track_total": str(track_pair[1] or ""),
        "disc": str(disc_pair[0] or ""),
        "disc_total": str(disc_pair[1] or ""),
        "bpm": _first_value(tags, "tmpo"),
        "compilation": bool((tags.get("cpil") or [False])[0]),
        "explicit": bool(tags.get("rtng")),
    }
    prefix = "----:com.apple.iTunes:"
    for key, value in tags.items():
        if not str(key).startswith(prefix):
            continue
        field = str(key)[len(prefix) :].casefold()
        if field in CUSTOM_FIELDS:
            result[field] = _first_value({field: value}, field)
    return {key: value for key, value in result.items() if value not in (None, "")}


def _read_vorbis_metadata(path: Path) -> dict[str, Any]:
    try:
        audio = MutagenFile(path, easy=False)
    except Exception:
        return {}
    if audio is None or audio.tags is None:
        return {}
    tags = audio.tags
    track, track_total_fraction = _split_fraction(_first_value(tags, "tracknumber"))
    disc, disc_total_fraction = _split_fraction(_first_value(tags, "discnumber"))
    result: dict[str, Any] = {
        "title": _first_value(tags, "title"),
        "artist": _first_value(tags, "artist"),
        "album": _first_value(tags, "album"),
        "album_artist": _first_value(tags, "albumartist"),
        "year": _first_value(tags, "date", "year"),
        "track": track,
        "track_total": _first_value(tags, "tracktotal", "totaltracks") or track_total_fraction,
        "disc": disc,
        "disc_total": _first_value(tags, "disctotal", "totaldiscs") or disc_total_fraction,
        "genre": _first_value(tags, "genre"),
        "composer": _first_value(tags, "composer"),
        "publisher": _first_value(tags, "organization", "publisher"),
        "copyright": _first_value(tags, "copyright"),
        "language": _first_value(tags, "language"),
        "comment": _first_value(tags, "comment"),
        "bpm": _first_value(tags, "bpm"),
        "isrc": _first_value(tags, "isrc"),
        "grouping": _first_value(tags, "grouping"),
        "source_url": _first_value(tags, "website", "source_url"),
        "encoded_by": _first_value(tags, "encodedby"),
        "compilation": _first_value(tags, "compilation"),
        "explicit": _first_value(tags, "explicit"),
    }
    for field in CUSTOM_FIELDS:
        value = _first_value(tags, field, field.upper())
        if value:
            result[field] = value
    return {key: value for key, value in result.items() if value not in (None, "")}


def read_embedded_metadata(path: str | Path) -> dict[str, Any]:
    """Read only metadata already present in a supported media file."""

    media_path = Path(path)
    suffix = media_path.suffix.lower()
    if suffix in {".mp3", ".wav"}:
        return _read_id3_metadata(media_path)
    if suffix in {".m4a", ".mp4"}:
        return _read_mp4_metadata(media_path)
    if suffix in {".flac", ".ogg", ".oga", ".opus"}:
        return _read_vorbis_metadata(media_path)
    return {}


def _positive_integer(value: Any) -> int | None:
    current, _ = _split_fraction(value)
    try:
        number = int(float(current))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _release_year(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"(?:19|20)\d{6}", text):
        return text[:4]
    match = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)
    return match.group(0) if match else ""


def prepare_metadata(
    embedded: Mapping[str, Any],
    *,
    enrich: bool = False,
    enricher: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prepare embedded tags conservatively, never synthesising a genre."""

    original = {str(key): _json_safe(value) for key, value in embedded.items()}
    prepared = dict(original)
    if enrich:
        enriched = dict((enricher or enrich_with_musicbrainz)(prepared))
        # Only the configured conservative enricher may add a missing genre;
        # YouTube categories/keywords are never considered a genre source.
        if not is_unknown(original.get("genre")):
            enriched["genre"] = original["genre"]
        prepared = enriched

    if is_unknown(prepared.get("album_artist")) and not is_unknown(prepared.get("artist")):
        prepared["album_artist"] = prepared["artist"]

    cleaned: dict[str, Any] = {}
    for key, value in prepared.items():
        if isinstance(value, str):
            value = value.strip()
            if is_unknown(value):
                continue
        if value not in (None, "", [], {}):
            cleaned[key] = value
    cleaned["year"] = _release_year(cleaned.get("year") or cleaned.get("date"))
    track = _positive_integer(cleaned.get("track"))
    if track is not None:
        cleaned["track"] = track
    return cleaned


def destination_for_metadata(root: Path, metadata: Mapping[str, Any], suffix: str) -> tuple[Path | None, list[str]]:
    """Build ``artist/year - album/track - title`` or report missing fields."""

    artist = safe_component(metadata.get("album_artist"))
    album = safe_component(metadata.get("album"))
    year = _release_year(metadata.get("year"))
    title = safe_component(metadata.get("title"))
    track = _positive_integer(metadata.get("track"))
    missing = [
        name
        for name, value in (
            ("album_artist", artist),
            ("year", year),
            ("album", album),
            ("track", track),
            ("title", title),
        )
        if not value
    ]
    if missing:
        return None, missing
    destination = root / artist / f"{year} - {album}" / f"{track:02d} - {title}{suffix.lower()}"
    return _within_root(root, destination), []


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False))).casefold()


def _fingerprint(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _entry_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:20]


def _iter_media(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        try:
            relative = path.relative_to(root)
            if relative.parts and relative.parts[0] == ".ymd-repair":
                continue
            resolved = _within_root(root, path)
            if resolved.is_file() and resolved.suffix.lower() in SUPPORTED_EXTENSIONS:
                yield resolved
        except (OSError, ValueError):
            continue


def build_repair_plan(
    root: str | Path,
    *,
    enrich: bool = False,
    enricher: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, non-mutating migration plan."""

    base = validate_library_root(root)
    entries: list[dict[str, Any]] = []
    for source in sorted(_iter_media(base), key=lambda item: item.relative_to(base).as_posix().casefold()):
        relative = source.relative_to(base).as_posix()
        embedded = read_embedded_metadata(source)
        prepared = prepare_metadata(embedded, enrich=enrich, enricher=enricher)
        destination, missing = destination_for_metadata(base, prepared, source.suffix)
        entry: dict[str, Any] = {
            "id": _entry_id(relative),
            "source": relative,
            "destination": destination.relative_to(base).as_posix() if destination else "",
            "status": "planned",
            "reason": "",
            "fingerprint": _fingerprint(source),
            "metadata_before": embedded,
            "metadata_after": prepared,
            "tag_backup": "",
            "action": "move_and_retag",
        }
        if missing:
            entry["status"] = "skipped"
            entry["reason"] = "missing:" + ",".join(missing)
        elif _path_key(source) == _path_key(destination):
            entry["status"] = "planned"
            entry["reason"] = "already_organized"
            entry["action"] = "retag_only"
        elif destination.exists():
            entry["status"] = "collision"
            entry["reason"] = "destination_exists"
        entries.append(entry)

    destinations: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if entry["status"] != "planned":
            continue
        destination = _within_root(base, base / entry["destination"])
        destinations.setdefault(_path_key(destination), []).append(entry)
    for duplicates in destinations.values():
        if len(duplicates) > 1:
            for entry in duplicates:
                entry["status"] = "collision"
                entry["reason"] = "duplicate_destination_in_plan"

    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "journal_id": str(uuid.uuid4()),
        "root": str(base),
        "mode": "dry-run",
        "enrich": bool(enrich),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "status": "planned",
        "entries": entries,
        "summary": _summary(entries),
    }


def _summary(entries: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {"total": 0}
    for entry in entries:
        summary["total"] += 1
        status = str(entry.get("status") or "unknown")
        summary[status] = summary.get(status, 0) + 1
    return summary


def default_journal_path(root: str | Path, journal_id: str) -> Path:
    base = validate_library_root(root)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return base / ".ymd-repair" / "journals" / f"{stamp}-{journal_id[:8]}.json"


def _backup_path(journal_path: Path, entry_id: str) -> Path:
    return journal_path.parent / f"{journal_path.stem}.tag-backups" / f"{entry_id}.json"


def _create_tag_backup(path: Path, destination: Path, metadata: Mapping[str, Any]) -> None:
    cover = read_embedded_cover(path)
    payload: dict[str, Any] = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "created_at": _utc_now(),
        "file_name": path.name,
        "fingerprint": _fingerprint(path),
        "metadata": metadata,
        "lyrics": read_embedded_lyrics(path),
        "cover": None,
    }
    if cover:
        data, mime = cover
        payload["cover"] = {
            "mime": mime,
            "sha256": hashlib.sha256(data).hexdigest(),
            "data_base64": base64.b64encode(data).decode("ascii"),
        }
    _atomic_write_json(destination, payload)


def _restore_tag_backup(path: Path, backup_path: Path) -> None:
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or {}
    write_metadata(path, metadata)
    lyrics = str(payload.get("lyrics") or "")
    if lyrics:
        write_lyrics(path, lyrics)


@contextmanager
def _repair_lock(root: Path):
    lock_path = root / ".ymd-repair" / "repair.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"Ya existe una migracion activa o interrumpida: {lock_path}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "created_at": _utc_now()}))
        yield
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass


def apply_repair_plan(
    plan: Mapping[str, Any],
    journal_path: str | Path,
    *,
    analyze_audio: bool = False,
    ffmpeg_path: str | Path = "ffmpeg",
) -> dict[str, Any]:
    """Apply a previously built plan without overwriting or leaving the root."""

    journal = dict(plan)
    entries = [dict(entry) for entry in plan.get("entries") or []]
    journal["entries"] = entries
    root = validate_library_root(str(plan.get("root") or ""))
    journal_file = Path(journal_path).expanduser().resolve(strict=False)
    journal["mode"] = "apply"
    journal["status"] = "running"
    journal["updated_at"] = _utc_now()
    _atomic_write_json(journal_file, journal)

    with _repair_lock(root):
        for entry in entries:
            if entry.get("status") != "planned":
                continue
            try:
                source = _within_root(root, root / str(entry["source"]))
                destination = _within_root(root, root / str(entry["destination"]))
                if not source.is_file():
                    raise FileNotFoundError("source_missing")
                retag_only = entry.get("action") == "retag_only"
                if destination.exists() and not (retag_only and destination == source):
                    raise FileExistsError("destination_exists")
                if _fingerprint(source) != entry.get("fingerprint"):
                    raise RuntimeError("source_changed_since_plan")

                backup = _backup_path(journal_file, str(entry["id"]))
                _create_tag_backup(source, backup, entry.get("metadata_before") or {})
                entry["tag_backup"] = os.path.relpath(backup, journal_file.parent).replace("\\", "/")
                entry["status"] = "backed_up"
                journal["updated_at"] = _utc_now()
                journal["summary"] = _summary(entries)
                _atomic_write_json(journal_file, journal)

                if not retag_only:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source.rename(destination)
                    entry["status"] = "moved"
                else:
                    destination = source
                    entry["status"] = "backed_up"
                journal["updated_at"] = _utc_now()
                journal["summary"] = _summary(entries)
                _atomic_write_json(journal_file, journal)

                metadata_after = dict(entry.get("metadata_after") or {})
                if analyze_audio:
                    analysis = analyze_loudness(destination, ffmpeg_path=ffmpeg_path)
                    metadata_after.update(analysis)
                    entry["audio_analysis_status"] = analysis.get("audio_analysis_status", "failed")
                    entry["metadata_after"] = metadata_after
                write_metadata(destination, metadata_after)
                entry["status"] = "completed"
                entry["completed_at"] = _utc_now()
            except Exception as exc:
                entry["status"] = "error"
                entry["reason"] = str(exc)
                # A move that succeeded but a retag that failed is put back at
                # its original location whenever it remains safe to do so.
                try:
                    source = _within_root(root, root / str(entry["source"]))
                    destination = _within_root(root, root / str(entry.get("destination") or ""))
                    backup_value = str(entry.get("tag_backup") or "")
                    if entry.get("action") == "retag_only" and source.is_file() and backup_value:
                        backup = (journal_file.parent / backup_value).resolve(strict=True)
                        _restore_tag_backup(source, backup)
                        entry["status"] = "rolled_back_after_error"
                        continue
                    if destination.is_file() and not source.exists():
                        if backup_value:
                            backup = (journal_file.parent / backup_value).resolve(strict=True)
                            _restore_tag_backup(destination, backup)
                        source.parent.mkdir(parents=True, exist_ok=True)
                        destination.rename(source)
                        entry["status"] = "rolled_back_after_error"
                except Exception as rollback_exc:
                    entry["rollback_error"] = str(rollback_exc)
            finally:
                journal["updated_at"] = _utc_now()
                journal["summary"] = _summary(entries)
                _atomic_write_json(journal_file, journal)

    journal["status"] = "completed_with_errors" if any(
        entry.get("status") in {"error", "rolled_back_after_error"} for entry in entries
    ) else "completed"
    journal["completed_at"] = _utc_now()
    journal["updated_at"] = journal["completed_at"]
    journal["summary"] = _summary(entries)
    _atomic_write_json(journal_file, journal)
    return journal


def repair_library(
    root: str | Path,
    *,
    apply: bool = False,
    enrich: bool = False,
    journal_path: str | Path | None = None,
    enricher: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    analyze_audio: bool = False,
    ffmpeg_path: str | Path = "ffmpeg",
) -> dict[str, Any]:
    """Plan a repair and optionally apply it.  Dry-run is the default."""

    plan = build_repair_plan(root, enrich=enrich, enricher=enricher)
    journal_file = (
        Path(journal_path).expanduser().resolve(strict=False)
        if journal_path
        else default_journal_path(plan["root"], plan["journal_id"])
    )
    if not apply:
        plan["journal_path"] = str(journal_file)
        _atomic_write_json(journal_file, plan)
        return plan
    result = apply_repair_plan(
        plan,
        journal_file,
        analyze_audio=analyze_audio,
        ffmpeg_path=ffmpeg_path,
    )
    result["journal_path"] = str(journal_file)
    return result


def rollback_library_repair(
    root: str | Path,
    source_journal: str | Path,
    *,
    journal_path: str | Path | None = None,
) -> dict[str, Any]:
    """Reverse completed moves from an apply journal, without overwriting."""

    base = validate_library_root(root)
    source_file = Path(source_journal).expanduser().resolve(strict=True)
    original = json.loads(source_file.read_text(encoding="utf-8"))
    recorded_root = validate_library_root(str(original.get("root") or ""))
    if recorded_root != base:
        raise ValueError("La raiz indicada no coincide con la del journal")

    rollback_entries: list[dict[str, Any]] = []
    result = {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "journal_id": str(uuid.uuid4()),
        "source_journal": str(source_file),
        "root": str(base),
        "mode": "rollback",
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "status": "running",
        "entries": rollback_entries,
        "summary": {},
    }
    output_file = (
        Path(journal_path).expanduser().resolve(strict=False)
        if journal_path
        else default_journal_path(base, result["journal_id"]).with_name(
            f"rollback-{result['journal_id'][:8]}.json"
        )
    )
    _atomic_write_json(output_file, result)

    with _repair_lock(base):
        for original_entry in reversed(original.get("entries") or []):
            if original_entry.get("status") not in {"completed", "moved", "backed_up"}:
                continue
            entry = {
                "id": original_entry.get("id"),
                "source": original_entry.get("destination"),
                "destination": original_entry.get("source"),
                "status": "planned",
                "reason": "",
            }
            rollback_entries.append(entry)
            try:
                current = _within_root(base, base / str(entry["source"]))
                destination = _within_root(base, base / str(entry["destination"]))
                backup_value = str(original_entry.get("tag_backup") or "")
                if original_entry.get("action") == "retag_only":
                    if not destination.is_file():
                        raise FileNotFoundError("retagged_file_missing")
                    if backup_value:
                        backup = (source_file.parent / backup_value).resolve(strict=True)
                        _restore_tag_backup(destination, backup)
                    entry["status"] = "completed"
                    entry["reason"] = "tags_restored"
                    continue
                if destination.is_file() and not current.exists() and original_entry.get("status") == "backed_up":
                    entry["status"] = "unchanged"
                    entry["reason"] = "move_not_started"
                    continue
                if not current.is_file():
                    raise FileNotFoundError("migrated_file_missing")
                if destination.exists():
                    raise FileExistsError("original_path_occupied")
                if backup_value:
                    backup = (source_file.parent / backup_value).resolve(strict=True)
                    try:
                        backup.relative_to(source_file.parent.resolve(strict=True))
                    except ValueError as exc:
                        raise ValueError("tag_backup_outside_journal_directory") from exc
                    _restore_tag_backup(current, backup)
                destination.parent.mkdir(parents=True, exist_ok=True)
                current.rename(destination)
                entry["status"] = "completed"
                entry["completed_at"] = _utc_now()
            except Exception as exc:
                entry["status"] = "error"
                entry["reason"] = str(exc)
            finally:
                result["updated_at"] = _utc_now()
                result["summary"] = _summary(rollback_entries)
                _atomic_write_json(output_file, result)

    result["status"] = "completed_with_errors" if any(
        entry.get("status") == "error" for entry in rollback_entries
    ) else "completed"
    result["completed_at"] = _utc_now()
    result["updated_at"] = result["completed_at"]
    result["summary"] = _summary(rollback_entries)
    result["journal_path"] = str(output_file)
    _atomic_write_json(output_file, result)
    return result
