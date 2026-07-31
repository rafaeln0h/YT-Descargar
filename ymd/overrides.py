"""User-owned metadata corrections used when public catalogues have gaps."""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping

ALLOWED_OVERRIDE_FIELDS = {
    "title",
    "artist",
    "album",
    "album_artist",
    "year",
    "release_date",
    "original_release_date",
    "track",
    "track_total",
    "disc",
    "disc_total",
    "genre",
    "composer",
    "lyricist",
    "producer",
    "publisher",
    "copyright",
    "language",
    "bpm",
    "isrc",
    "grouping",
    "compilation",
    "explicit",
    "release_type",
    "release_country",
    "release_status",
    "catalog_number",
    "barcode",
    "mood",
}
MATCH_FIELDS = {"youtube_id", "artist", "album", "title"}


def normalized_identity(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def load_overrides(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    if not source.exists():
        return {"version": 1, "entries": []}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "entries": []}
    entries = payload.get("entries") if isinstance(payload, dict) else []
    return {
        "version": 1,
        "entries": [entry for entry in (entries or []) if isinstance(entry, dict)],
    }


def _entry_matches(metadata: Mapping[str, Any], match: Mapping[str, Any]) -> bool:
    compared = 0
    for field in MATCH_FIELDS:
        expected = match.get(field)
        if expected in (None, ""):
            continue
        compared += 1
        actual = metadata.get(field)
        if field == "youtube_id":
            if str(actual or "").strip() != str(expected).strip():
                return False
        elif normalized_identity(actual) != normalized_identity(expected):
            return False
    return compared > 0


def apply_metadata_overrides(
    metadata: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply matching user corrections, with specific entries winning last."""

    result = dict(metadata)
    matching = []
    for entry in overrides.get("entries", []):
        match = entry.get("match") or {}
        if isinstance(match, dict) and _entry_matches(result, match):
            specificity = sum(1 for field in MATCH_FIELDS if match.get(field) not in (None, ""))
            matching.append((specificity, entry))
    for _, entry in sorted(matching, key=lambda item: item[0]):
        replace = bool(entry.get("replace", True))
        for field, value in (entry.get("values") or {}).items():
            if field not in ALLOWED_OVERRIDE_FIELDS or value in (None, ""):
                continue
            if replace or result.get(field) in (None, "", "Unknown"):
                result[field] = value
                result[f"{field}_source"] = "user_override"
        sources = [part.strip() for part in str(result.get("metadata_sources_used") or "").split(";")]
        if "manual" not in sources:
            sources.append("manual")
        result["metadata_sources_used"] = "; ".join(part for part in sources if part)
    return result


def upsert_override(path: str | Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    match = {
        key: str(value).strip()
        for key, value in dict(entry.get("match") or {}).items()
        if key in MATCH_FIELDS and str(value or "").strip()
    }
    values = {
        key: value
        for key, value in dict(entry.get("values") or {}).items()
        if key in ALLOWED_OVERRIDE_FIELDS and value not in (None, "")
    }
    if not match or not values:
        raise ValueError("La correccion necesita al menos una coincidencia y un valor permitido")

    payload = load_overrides(path)
    identity = json.dumps(match, sort_keys=True, ensure_ascii=False)
    replacement = {"match": match, "values": values, "replace": bool(entry.get("replace", True))}
    entries = payload["entries"]
    for index, current in enumerate(entries):
        current_identity = json.dumps(current.get("match") or {}, sort_keys=True, ensure_ascii=False)
        if current_identity == identity:
            entries[index] = replacement
            break
    else:
        entries.append(replacement)

    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(destination)
    return replacement
