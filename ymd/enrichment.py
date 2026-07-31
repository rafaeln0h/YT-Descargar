"""Conservative, optional metadata enrichment.

MusicBrainz remains the authoritative open metadata source.  The public
functions keep the original flat return value for current callers, while the
``enrich_metadata`` orchestrator exposes field-level provenance, confidence and
missing fields for future download and library pipelines.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import requests

from .version import VERSION

LOGGER = logging.getLogger(__name__)
MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2"
MUSICBRAINZ_SEARCH_URL = f"{MUSICBRAINZ_BASE_URL}/recording/"
USER_AGENT = f"YT-Descargar/{VERSION} (https://github.com/rafaeln0h/YT-Descargar)"

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0

RICH_FIELDS = (
    "title",
    "artist",
    "album",
    "album_artist",
    "year",
    "release_date",
    "release_country",
    "release_status",
    "release_type",
    "publisher",
    "catalog_number",
    "barcode",
    "language",
    "track",
    "track_total",
    "disc",
    "disc_total",
    "isrc",
    "genre",
    "genres",
    "styles",
    "composer",
    "credits",
    "explicit",
)


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(
        r"\([^)]*(official|oficial|video|audio|lyrics?|visuali[sz]er)[^)]*\)",
        "",
        text,
    )
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _lucene_phrase(value: str) -> str:
    """Escape the two characters that can terminate a quoted Lucene phrase."""

    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _artist_credit(entity: Mapping[str, Any]) -> tuple[str, list[str]]:
    names: list[str] = []
    ids: list[str] = []
    for credit in entity.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist") or {}
        name = credit.get("name") or artist.get("name")
        if name:
            names.append(str(name))
        if artist.get("id"):
            ids.append(str(artist["id"]))
    return "; ".join(names), ids


def _artist_matches(entity: Mapping[str, Any], requested_artist: str) -> bool:
    wanted = _normalized(requested_artist)
    if not wanted:
        return False
    credited, _ = _artist_credit(entity)
    if _normalized(credited) == wanted:
        return True
    individual = []
    for credit in entity.get("artist-credit") or []:
        if isinstance(credit, dict):
            artist = credit.get("artist") or {}
            individual.append(_normalized(credit.get("name") or artist.get("name")))
    return wanted in {name for name in individual if name}


def _release_score(release: Mapping[str, Any], requested_album: str) -> int:
    score = 0
    wanted = _normalized(requested_album)
    title = _normalized(release.get("title"))
    if wanted and wanted != "unknown":
        if title == wanted:
            score += 100
        elif wanted in title or title in wanted:
            score += 20
    if str(release.get("status") or "").casefold() == "official":
        score += 15
    if release.get("date"):
        score += 3
    release_group = release.get("release-group") or {}
    if str(release_group.get("primary-type") or "").casefold() in {
        "album",
        "ep",
        "single",
    }:
        score += 2
    return score


def _pick_release(recording: Mapping[str, Any], album: str) -> Mapping[str, Any]:
    releases = [item for item in (recording.get("releases") or []) if isinstance(item, dict)]
    if not releases:
        return {}

    def release_rank(release: Mapping[str, Any]) -> tuple[int, int]:
        # For otherwise equivalent official editions, the earliest dated
        # release is the safest source for the original album year.
        digits = re.sub(r"\D", "", str(release.get("date") or ""))[:8]
        date_rank = int(digits.ljust(8, "9")) if digits else 99_999_999
        return _release_score(release, album), -date_rank

    return max(releases, key=release_rank)


def _genres(*entities: Mapping[str, Any]) -> list[str]:
    """Return only MusicBrainz genres, never arbitrary tags/categories."""

    ranked: dict[str, tuple[int, str]] = {}
    for entity in entities:
        for item in entity.get("genres") or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = str(item["name"]).strip()
            key = _normalized(name)
            if not key:
                continue
            try:
                votes = int(item.get("count") or 0)
            except (TypeError, ValueError):
                votes = 0
            previous = ranked.get(key)
            if previous is None or votes > previous[0]:
                ranked[key] = (votes, name)
    return [item[1] for item in sorted(ranked.values(), key=lambda item: (-item[0], item[1]))]


def _relation_credits(entity: Mapping[str, Any], *, scope: str) -> list[dict[str, str]]:
    credits: list[dict[str, str]] = []
    for relation in entity.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        artist = relation.get("artist") or {}
        if artist.get("name"):
            role = str(relation.get("type") or "credit").strip().casefold()
            attributes = [str(value) for value in relation.get("attributes") or [] if value]
            credits.append(
                {
                    "name": str(artist["name"]),
                    "artist_id": str(artist.get("id") or ""),
                    "role": role,
                    "detail": "; ".join(attributes),
                    "scope": scope,
                }
            )
        work = relation.get("work") or {}
        if isinstance(work, dict):
            credits.extend(_relation_credits(work, scope="work"))
    unique: dict[tuple[str, str, str], dict[str, str]] = {}
    for credit in credits:
        key = (_normalized(credit["name"]), credit["role"], credit["scope"])
        unique[key] = credit
    return list(unique.values())


def _track_position(
    release: Mapping[str, Any],
    recording_id: str,
) -> tuple[Any, Any, Any, Any]:
    media = [item for item in release.get("media") or [] if isinstance(item, dict)]
    for disc_index, medium in enumerate(media, 1):
        tracks = [item for item in medium.get("tracks") or [] if isinstance(item, dict)]
        for track_index, track in enumerate(tracks, 1):
            linked = track.get("recording") or {}
            if str(linked.get("id") or "") != recording_id:
                continue
            return (
                track.get("position") or track.get("number") or track_index,
                medium.get("track-count") or len(tracks),
                medium.get("position") or disc_index,
                len(media),
            )
    first = media[0] if media else {}
    return "", first.get("track-count", ""), "", len(media) if media else ""


def parse_musicbrainz_recording(
    recording: Mapping[str, Any],
    *,
    requested_album: str = "",
    release_detail: Mapping[str, Any] | None = None,
    release_group_detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Translate verified MusicBrainz entities into the neutral tag model."""

    artist_name, artist_ids = _artist_credit(recording)
    selected_release = _pick_release(recording, requested_album)
    release = dict(selected_release)
    if release_detail and (not selected_release or release_detail.get("id") == selected_release.get("id")):
        release.update(dict(release_detail))
    release_group = dict(release.get("release-group") or {})
    if release_group_detail and (
        not release_group or release_group_detail.get("id") == release_group.get("id")
    ):
        release_group.update(dict(release_group_detail))

    release_artist, _ = _artist_credit(release)
    label_info = [item for item in release.get("label-info") or [] if isinstance(item, dict)]
    labels: list[str] = []
    catalog_numbers: list[str] = []
    for item in label_info:
        label = item.get("label") or {}
        if label.get("name"):
            labels.append(str(label["name"]))
        if item.get("catalog-number"):
            catalog_numbers.append(str(item["catalog-number"]))
    text_representation = release.get("text-representation") or {}
    isrcs = [str(value) for value in recording.get("isrcs") or [] if value]
    genres = _genres(recording, release, release_group)
    credits = _relation_credits(recording, scope="recording")
    track, track_total, disc, disc_total = _track_position(
        release,
        str(recording.get("id") or ""),
    )
    composers = sorted(
        {credit["name"] for credit in credits if credit["role"] in {"composer", "writer", "music"}}
    )

    release_date = str(release.get("date") or recording.get("first-release-date") or "")
    original_release_date = str(
        release_group.get("first-release-date")
        or recording.get("first-release-date")
        or release_date
        or ""
    )
    result = {
        "musicbrainz_recordingid": recording.get("id", ""),
        "musicbrainz_releaseid": release.get("id", ""),
        "musicbrainz_releasegroupid": release_group.get("id", ""),
        "musicbrainz_artistids": ";".join(artist_ids),
        "musicbrainz_score": recording.get("score", ""),
        "artist": artist_name,
        "album_artist": release_artist or artist_name,
        "album": release.get("title", ""),
        "year": release_date[:4],
        "release_date": release_date,
        "original_release_date": original_release_date,
        "release_country": release.get("country", ""),
        "release_status": release.get("status", ""),
        "release_type": release_group.get("primary-type", ""),
        "publisher": "; ".join(dict.fromkeys(labels)),
        "catalog_number": "; ".join(dict.fromkeys(catalog_numbers)),
        "barcode": release.get("barcode", ""),
        "language": text_representation.get("language", ""),
        "track": track,
        "track_total": track_total,
        "disc": disc,
        "disc_total": disc_total,
        "isrc": isrcs[0] if isrcs else "",
        "isrcs": isrcs,
        "genre": genres[0] if genres else "",
        "genres": genres,
        "composer": "; ".join(composers),
        "credits": credits,
    }
    return {key: value for key, value in result.items() if value not in ("", None, [])}


def _rate_limited_get(
    url: str,
    params: Mapping[str, Any],
    timeout: int,
) -> requests.Response:
    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        delay = 1.05 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            time.sleep(delay)
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        _LAST_REQUEST_AT = time.monotonic()
    return response


def _musicbrainz_get(url: str, params: Mapping[str, Any], timeout: int) -> dict[str, Any]:
    response = _rate_limited_get(url, params, timeout)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _candidate_confidence(
    candidate: Mapping[str, Any],
    *,
    artist: str,
    title: str,
    album: str,
) -> float:
    try:
        search_score = max(0, min(int(candidate.get("score") or 0), 100))
    except (TypeError, ValueError):
        search_score = 0
    if _normalized(candidate.get("title")) != _normalized(title):
        return 0.0
    if not _artist_matches(candidate, artist):
        return 0.0
    confidence = search_score / 100
    selected_release = _pick_release(candidate, album)
    if album and _normalized(selected_release.get("title")) == _normalized(album):
        confidence = min(1.0, confidence + 0.03)
    return round(confidence, 3)


@lru_cache(maxsize=512)
def search_musicbrainz_recording(
    artist: str,
    title: str,
    album: str = "",
    *,
    timeout: int = 10,
) -> dict[str, Any]:
    clean_artist = str(artist or "").strip()
    clean_title = str(title or "").strip()
    clean_album = str(album or "").strip()
    if not clean_artist or not clean_title or clean_artist == "Unknown" or clean_title == "Unknown":
        return {}

    clauses = [
        f'recording:"{_lucene_phrase(clean_title)}"',
        f'artist:"{_lucene_phrase(clean_artist)}"',
    ]
    if clean_album and clean_album != "Unknown":
        clauses.append(f'release:"{_lucene_phrase(clean_album)}"')
    try:
        payload = _musicbrainz_get(
            MUSICBRAINZ_SEARCH_URL,
            {"query": " AND ".join(clauses), "fmt": "json", "limit": 8},
            timeout,
        )
    except Exception as exc:
        LOGGER.warning("MusicBrainz search failed for %s - %s: %s", clean_artist, clean_title, exc)
        return {}

    ranked: list[tuple[float, Mapping[str, Any]]] = []
    for candidate in payload.get("recordings") or []:
        if not isinstance(candidate, dict):
            continue
        confidence = _candidate_confidence(
            candidate,
            artist=clean_artist,
            title=clean_title,
            album=clean_album,
        )
        if confidence >= 0.90:
            ranked.append((confidence, candidate))
    if not ranked:
        return {}
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = dict(ranked[0][1])
    selected["_confidence"] = ranked[0][0]
    return selected


@lru_cache(maxsize=1024)
def lookup_musicbrainz_entity(
    entity: str,
    entity_id: str,
    *,
    timeout: int = 10,
) -> dict[str, Any]:
    includes = {
        "recording": ("artists+isrcs+releases+release-groups+genres+artist-rels+work-rels+work-level-rels"),
        "release": (
            "labels+recordings+release-groups+media+isrcs+artist-credits+genres+"
            "recording-level-rels+work-rels+artist-rels+work-level-rels"
        ),
        "release-group": "artist-credits+genres+artist-rels",
    }
    if entity not in includes or not entity_id:
        return {}
    try:
        return _musicbrainz_get(
            f"{MUSICBRAINZ_BASE_URL}/{entity}/{entity_id}",
            {"fmt": "json", "inc": includes[entity]},
            timeout,
        )
    except Exception as exc:
        LOGGER.warning("MusicBrainz %s lookup failed for %s: %s", entity, entity_id, exc)
        return {}


@lru_cache(maxsize=512)
def lookup_musicbrainz(
    artist: str,
    title: str,
    album: str = "",
    *,
    timeout: int = 10,
    detailed: bool = False,
) -> dict[str, Any]:
    """Return a high-confidence MusicBrainz match or an empty dictionary.

    ``detailed=False`` preserves the low-latency behavior used by current
    downloads.  Future callers can opt into release/release-group lookups.
    """

    cached_candidate = search_musicbrainz_recording(artist, title, album, timeout=timeout)
    candidate = dict(cached_candidate)
    if not candidate:
        return {}
    confidence = float(candidate.pop("_confidence", 0.0))
    recording = candidate
    release_detail: dict[str, Any] = {}
    release_group_detail: dict[str, Any] = {}
    if detailed:
        detailed_recording = lookup_musicbrainz_entity(
            "recording",
            str(candidate.get("id") or ""),
            timeout=timeout,
        )
        if detailed_recording:
            detailed_recording["score"] = candidate.get("score", "")
            recording = detailed_recording
        selected_release = _pick_release(recording, album) or _pick_release(candidate, album)
        release_id = str(selected_release.get("id") or "")
        if release_id:
            release_detail = lookup_musicbrainz_entity("release", release_id, timeout=timeout)
        release_group = (release_detail or selected_release).get("release-group") or {}
        release_group_id = str(release_group.get("id") or "")
        if release_group_id:
            release_group_detail = lookup_musicbrainz_entity(
                "release-group",
                release_group_id,
                timeout=timeout,
            )
    parsed = parse_musicbrainz_recording(
        recording,
        requested_album=album,
        release_detail=release_detail,
        release_group_detail=release_group_detail,
    )
    parsed["enrichment_confidence"] = confidence
    return parsed


def _provider_result(
    provider: str,
    fields: Mapping[str, Any],
    *,
    confidence: float,
    reference: str = "",
    status: str = "ok",
    reason: str = "",
) -> dict[str, Any]:
    clean_fields = {key: value for key, value in dict(fields).items() if value not in ("", None, [])}
    return {
        "provider": provider,
        "status": status,
        "fields": clean_fields,
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 3),
        "reference": reference,
        "reason": reason,
    }


def musicbrainz_enrichment(
    metadata: Mapping[str, Any],
    *,
    detailed: bool = True,
    timeout: int = 10,
) -> dict[str, Any]:
    match = dict(
        lookup_musicbrainz(
            str(metadata.get("artist") or ""),
            str(metadata.get("title") or ""),
            str(metadata.get("album") or ""),
            timeout=timeout,
            detailed=detailed,
        )
    )
    if not match:
        return _provider_result(
            "musicbrainz",
            {},
            confidence=0,
            status="not_found",
            reason="No high-confidence recording match",
        )
    confidence = float(match.pop("enrichment_confidence", 0.9))
    return _provider_result(
        "musicbrainz",
        match,
        confidence=confidence,
        reference=str(match.get("musicbrainz_recordingid") or ""),
    )


def _merge_provider(
    merged: dict[str, Any],
    provenance: dict[str, Any],
    result: Mapping[str, Any],
) -> None:
    if result.get("status") != "ok":
        return
    confidence = float(result.get("confidence") or 0)
    for key, value in dict(result.get("fields") or {}).items():
        current_is_empty = merged.get(key) in ("", None, "Unknown")
        if key == "explicit" and not merged.get("explicit_known"):
            current_is_empty = True
        if not current_is_empty:
            continue
        merged[key] = value
        provenance[key] = {
            "source": result.get("provider"),
            "confidence": confidence,
            "reference": result.get("reference") or "",
        }


def enrich_metadata(
    metadata: Mapping[str, Any],
    *,
    audio_path: str | Path | None = None,
    use_musicbrainz: bool = True,
    use_ytmusic: bool = True,
    use_acoustid: bool = True,
    use_discogs: bool = True,
    acoustid_api_key: str = "",
    discogs_token: str = "",
    detailed_musicbrainz: bool = True,
    timeout: int = 10,
) -> dict[str, Any]:
    """Run optional providers and return metadata plus an audit envelope.

    Existing non-empty values win.  Provider suggestions remain available in
    ``providers[*].fields`` even when they are not applied.
    """

    merged = dict(metadata)
    provenance: dict[str, Any] = {}
    providers: list[dict[str, Any]] = []
    musicbrainz_result: dict[str, Any] | None = None

    if use_musicbrainz:
        result = musicbrainz_enrichment(
            merged,
            detailed=detailed_musicbrainz,
            timeout=timeout,
        )
        providers.append(result)
        musicbrainz_result = dict(result)
        _merge_provider(merged, provenance, result)

    if use_ytmusic:
        try:
            from .ytmusic import lookup_ytmusic_album

            result = lookup_ytmusic_album(merged)
        except Exception as exc:  # optional dependency/provider must never abort
            LOGGER.warning("Optional YouTube Music enrichment failed: %s", exc)
            result = _provider_result(
                "ytmusicapi", {}, confidence=0, status="error", reason=type(exc).__name__
            )
        providers.append(result)
        _merge_provider(merged, provenance, result)
    if use_acoustid:
        try:
            from .acoustid import lookup_acoustid_file

            result = lookup_acoustid_file(
                audio_path,
                api_key=acoustid_api_key,
                timeout=timeout,
            )
        except Exception as exc:  # optional binary/service must never abort
            LOGGER.warning("Optional AcoustID enrichment failed: %s", exc)
            result = _provider_result("acoustid", {}, confidence=0, status="error", reason=type(exc).__name__)
        providers.append(result)
        _merge_provider(merged, provenance, result)
        acoustid_recording_id = str(
            (result.get("fields") or {}).get("musicbrainz_recordingid") or ""
        )
        if (
            acoustid_recording_id
            and (not musicbrainz_result or musicbrainz_result.get("status") != "ok")
        ):
            recording = lookup_musicbrainz_entity(
                "recording",
                acoustid_recording_id,
                timeout=timeout,
            )
            if recording:
                recording["score"] = round(float(result.get("confidence") or 0) * 100)
                fields = parse_musicbrainz_recording(
                    recording,
                    requested_album=str(merged.get("album") or ""),
                )
                via_fingerprint = _provider_result(
                    "musicbrainz_via_acoustid",
                    fields,
                    confidence=float(result.get("confidence") or 0),
                    reference=acoustid_recording_id,
                )
                providers.append(via_fingerprint)
                _merge_provider(merged, provenance, via_fingerprint)

    if use_discogs:
        try:
            from .discogs import lookup_discogs_release

            result = lookup_discogs_release(
                merged,
                token=discogs_token,
                timeout=timeout,
            )
        except Exception as exc:  # optional token/service must never abort
            LOGGER.warning("Optional Discogs enrichment failed: %s", exc)
            result = _provider_result("discogs", {}, confidence=0, status="error", reason=type(exc).__name__)
        providers.append(result)
        _merge_provider(merged, provenance, result)

    unavailable = sorted(field for field in RICH_FIELDS if merged.get(field) in ("", None, [], "Unknown"))
    return {
        "metadata": merged,
        "provenance": provenance,
        "confidence": {field: details["confidence"] for field, details in provenance.items()},
        "unavailable": unavailable,
        "providers": providers,
    }


def enrich_with_musicbrainz(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Backward-compatible, low-latency MusicBrainz enrichment."""

    merged = dict(metadata)
    result = musicbrainz_enrichment(merged, detailed=False)
    provenance_fields = {
        "musicbrainz_recordingid",
        "musicbrainz_releaseid",
        "musicbrainz_releasegroupid",
        "musicbrainz_artistids",
        "musicbrainz_score",
    }
    for key, value in dict(result.get("fields") or {}).items():
        if key in provenance_fields or merged.get(key) in ("", None, "Unknown"):
            merged[key] = value
    return merged
