"""Responsible, optional lyrics enrichment through LRCLIB."""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from functools import lru_cache
from typing import Any, Mapping

import requests

from .version import VERSION

LOGGER = logging.getLogger(__name__)
LRCLIB_GET_URL = "https://lrclib.net/api/get"
LRCLIB_SEARCH_URL = "https://lrclib.net/api/search"
USER_AGENT = f"YT-Descargar/{VERSION} (https://github.com/rafaeln0h/YT-Descargar)"

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


def _plain_synced_lyrics(value: Any) -> str:
    lines: list[str] = []
    for raw_line in str(value or "").splitlines():
        line = re.sub(r"^(?:\[\d{2}:\d{2}(?:\.\d+)?\])+", "", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = re.sub(r"\([^)]*(official|video|audio|lyrics?|visuali[sz]er)[^)]*\)", "", text)
    text = re.sub(r"\b(official|oficial|topic|canal)\b", "", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def parse_lrclib_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the fields safe and useful for embedding."""

    if payload.get("instrumental") is True:
        return {"instrumental": True, "lrclib_id": payload.get("id", "")}
    lyrics = str(payload.get("plainLyrics") or "").strip()
    if not lyrics:
        lyrics = _plain_synced_lyrics(payload.get("syncedLyrics"))
    if not lyrics:
        return {}
    return {
        "lyrics": lyrics,
        "lrclib_id": payload.get("id", ""),
        "track_name": payload.get("trackName", ""),
        "artist_name": payload.get("artistName", ""),
        "album_name": payload.get("albumName", ""),
    }


def pick_lrclib_candidate(
    candidates: list[Mapping[str, Any]],
    *,
    artist: str,
    title: str,
    duration: int,
) -> dict[str, Any]:
    """Select a conservative search result when exact lookup misses."""

    wanted_artist = _normalized(artist)
    wanted_title = _normalized(title)
    ranked: list[tuple[int, Mapping[str, Any]]] = []
    for candidate in candidates:
        candidate_artist = _normalized(candidate.get("artistName"))
        candidate_title = _normalized(candidate.get("trackName"))
        if candidate_title != wanted_title:
            continue
        artist_matches = (
            candidate_artist == wanted_artist
            or candidate_artist in wanted_artist
            or wanted_artist in candidate_artist
        )
        if not artist_matches:
            continue
        try:
            duration_delta = abs(float(candidate.get("duration") or 0) - float(duration))
        except (TypeError, ValueError):
            continue
        if duration_delta > 3:
            continue
        score = 100 - int(duration_delta * 10)
        if candidate_artist == wanted_artist:
            score += 20
        ranked.append((score, candidate))
    if not ranked:
        return {}
    ranked.sort(key=lambda item: item[0], reverse=True)
    return parse_lrclib_payload(ranked[0][1])


def _get_with_rate_limit(
    url: str,
    params: Mapping[str, Any],
    timeout: int,
) -> requests.Response:
    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        delay = 0.4 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            time.sleep(delay)
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        _LAST_REQUEST_AT = time.monotonic()
        if response.status_code == 429:
            try:
                retry_after = min(max(float(response.headers.get("Retry-After", "1")), 0.5), 10)
            except (TypeError, ValueError):
                retry_after = 1
            time.sleep(retry_after)
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=timeout,
            )
            _LAST_REQUEST_AT = time.monotonic()
        return response


@lru_cache(maxsize=512)
def lookup_lrclib(
    artist: str,
    title: str,
    album: str,
    duration: int,
    *,
    timeout: int = 12,
) -> dict[str, Any]:
    """Get an exact-signature lyrics match without scraping websites."""

    clean_artist = str(artist or "").strip()
    clean_title = str(title or "").strip()
    clean_album = str(album or "").strip()
    try:
        clean_duration = max(1, int(float(duration)))
    except (TypeError, ValueError):
        return {}
    if (
        not clean_artist
        or not clean_title
        or clean_artist == "Unknown"
        or clean_title == "Unknown"
    ):
        return {}

    try:
        response = _get_with_rate_limit(
            LRCLIB_GET_URL,
            {
                "artist_name": clean_artist,
                "track_name": clean_title,
                "album_name": clean_album,
                "duration": clean_duration,
            },
            timeout,
        )
        if response.status_code != 404:
            response.raise_for_status()
            return parse_lrclib_payload(response.json())

        search_response = _get_with_rate_limit(
            LRCLIB_SEARCH_URL,
            {
                "artist_name": re.sub(
                    r"\b(official|oficial|topic|canal)\b",
                    "",
                    clean_artist,
                    flags=re.IGNORECASE,
                ).strip(),
                "track_name": clean_title,
            },
            timeout,
        )
        search_response.raise_for_status()
        candidates = search_response.json()
        if not isinstance(candidates, list):
            return {}
        return pick_lrclib_candidate(
            candidates,
            artist=clean_artist,
            title=clean_title,
            duration=clean_duration,
        )
    except Exception as exc:
        LOGGER.warning("LRCLIB lookup failed for %s - %s: %s", clean_artist, clean_title, exc)
        return {}
