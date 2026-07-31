"""Optional metadata enrichment from the public MusicBrainz web service."""

from __future__ import annotations

import logging
import re
import threading
import time
from functools import lru_cache
from typing import Any, Mapping

import requests

from .version import VERSION

LOGGER = logging.getLogger(__name__)
MUSICBRAINZ_SEARCH_URL = "https://musicbrainz.org/ws/2/recording/"
USER_AGENT = f"YT-Descargar/{VERSION} (https://github.com/rafaeln0h/YT-Descargar)"

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


def _normalized(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"\([^)]*(official|video|audio|lyrics?|visuali[sz]er)[^)]*\)", "", text)
    return re.sub(r"[^a-z0-9áéíóúüñ]+", " ", text).strip()


def _artist_credit(recording: Mapping[str, Any]) -> tuple[str, list[str]]:
    names: list[str] = []
    ids: list[str] = []
    for credit in recording.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        artist = credit.get("artist") or {}
        name = credit.get("name") or artist.get("name")
        if name:
            names.append(str(name))
        if artist.get("id"):
            ids.append(str(artist["id"]))
    return "; ".join(names), ids


def _pick_release(recording: Mapping[str, Any], album: str) -> Mapping[str, Any]:
    releases = [item for item in (recording.get("releases") or []) if isinstance(item, dict)]
    if not releases:
        return {}
    wanted = _normalized(album)
    if wanted and wanted != "unknown":
        for release in releases:
            if _normalized(release.get("title")) == wanted:
                return release
    official = [release for release in releases if release.get("status") == "Official"]
    return official[0] if official else releases[0]


def parse_musicbrainz_recording(
    recording: Mapping[str, Any],
    *,
    requested_album: str = "",
) -> dict[str, Any]:
    """Translate a MusicBrainz search result into our neutral tag model."""

    artist_name, artist_ids = _artist_credit(recording)
    release = _pick_release(recording, requested_album)
    release_group = release.get("release-group") or {}
    media = release.get("media") or []
    first_media = media[0] if media and isinstance(media[0], dict) else {}
    label_info = release.get("label-info") or []
    first_label = label_info[0] if label_info and isinstance(label_info[0], dict) else {}
    label = first_label.get("label") or {}
    text_representation = release.get("text-representation") or {}
    tags = sorted(
        (
            item
            for item in (recording.get("tags") or [])
            if isinstance(item, dict) and item.get("name")
        ),
        key=lambda item: int(item.get("count") or 0),
        reverse=True,
    )
    isrcs = recording.get("isrcs") or []

    result = {
        "musicbrainz_recordingid": recording.get("id", ""),
        "musicbrainz_releaseid": release.get("id", ""),
        "musicbrainz_releasegroupid": release_group.get("id", ""),
        "musicbrainz_artistids": ";".join(artist_ids),
        "musicbrainz_score": recording.get("score", ""),
        "artist": artist_name,
        "album": release.get("title", ""),
        "year": str(release.get("date") or recording.get("first-release-date") or "")[:4],
        "release_date": release.get("date") or recording.get("first-release-date") or "",
        "release_country": release.get("country", ""),
        "release_status": release.get("status", ""),
        "release_type": release_group.get("primary-type", ""),
        "publisher": label.get("name", ""),
        "catalog_number": first_label.get("catalog-number", ""),
        "barcode": release.get("barcode", ""),
        "language": text_representation.get("language", ""),
        "track_total": first_media.get("track-count", ""),
        "disc_total": len(media) if media else "",
        "isrc": isrcs[0] if isrcs else "",
        "genre": tags[0].get("name", "") if tags else "",
        "genres": [item["name"] for item in tags[:8]],
    }
    return {key: value for key, value in result.items() if value not in ("", None, [])}


def _rate_limited_get(params: Mapping[str, Any], timeout: int) -> requests.Response:
    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        delay = 1.05 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            time.sleep(delay)
        response = requests.get(
            MUSICBRAINZ_SEARCH_URL,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        _LAST_REQUEST_AT = time.monotonic()
    return response


@lru_cache(maxsize=512)
def lookup_musicbrainz(
    artist: str,
    title: str,
    album: str = "",
    *,
    timeout: int = 10,
) -> dict[str, Any]:
    """Return a high-confidence MusicBrainz match or an empty dictionary."""

    clean_artist = str(artist or "").strip()
    clean_title = str(title or "").strip()
    if not clean_artist or not clean_title or clean_artist == "Unknown" or clean_title == "Unknown":
        return {}

    query = f'recording:"{clean_title}" AND artist:"{clean_artist}"'
    try:
        response = _rate_limited_get(
            {"query": query, "fmt": "json", "limit": 5},
            timeout,
        )
        response.raise_for_status()
        candidates = response.json().get("recordings") or []
    except Exception as exc:
        LOGGER.warning("MusicBrainz lookup failed for %s - %s: %s", clean_artist, clean_title, exc)
        return {}

    requested_title = _normalized(clean_title)
    requested_artist = _normalized(clean_artist)
    for candidate in candidates:
        score = int(candidate.get("score") or 0)
        candidate_artist, _ = _artist_credit(candidate)
        title_matches = _normalized(candidate.get("title")) == requested_title
        artist_matches = requested_artist in _normalized(candidate_artist)
        if score >= 90 and title_matches and artist_matches:
            return parse_musicbrainz_recording(candidate, requested_album=album)
    return {}


def enrich_with_musicbrainz(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Fill blank fields with a verified MusicBrainz match."""

    merged = dict(metadata)
    match = lookup_musicbrainz(
        str(merged.get("artist") or ""),
        str(merged.get("title") or ""),
        str(merged.get("album") or ""),
    )
    if not match:
        return merged

    always_provenance = {
        "musicbrainz_recordingid",
        "musicbrainz_releaseid",
        "musicbrainz_releasegroupid",
        "musicbrainz_artistids",
        "musicbrainz_score",
    }
    for key, value in match.items():
        if key in always_provenance or merged.get(key) in ("", None, "Unknown"):
            merged[key] = value
    return merged
