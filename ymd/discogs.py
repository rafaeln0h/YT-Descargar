"""Optional exact album fallback using the Discogs database API."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import unicodedata
from typing import Any, Mapping

import requests

from .version import VERSION

LOGGER = logging.getLogger(__name__)
DISCOGS_SEARCH_URL = "https://api.discogs.com/database/search"
USER_AGENT = f"YT-Descargar/{VERSION} +https://github.com/rafaeln0h/YT-Descargar"

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _provider_result(
    fields: Mapping[str, Any],
    *,
    confidence: float = 0,
    reference: str = "",
    status: str = "ok",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "provider": "discogs",
        "status": status,
        "fields": {key: value for key, value in dict(fields).items() if value not in ("", None, [])},
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 3),
        "reference": reference,
        "reason": reason,
    }


def _exact_release(result: Mapping[str, Any], artist: str, album: str) -> bool:
    # Discogs search titles use the display form "Artist - Release".  Compare
    # the complete normalized identity so a same-name release by another artist
    # is never accepted.
    return _normalized(result.get("title")) == _normalized(f"{artist} - {album}")


def parse_discogs_result(result: Mapping[str, Any]) -> dict[str, Any]:
    genres = [str(value) for value in result.get("genre") or [] if value]
    styles = [str(value) for value in result.get("style") or [] if value]
    labels = [str(value) for value in result.get("label") or [] if value]
    fields: dict[str, Any] = {
        "genres": genres,
        "styles": styles,
        "genre": genres[0] if genres else "",
        "year": result.get("year", ""),
        "publisher": "; ".join(dict.fromkeys(labels)),
        "catalog_number": result.get("catno", ""),
    }
    return {key: value for key, value in fields.items() if value not in ("", None, [])}


def _rate_limited_get(
    *,
    params: Mapping[str, Any],
    token: str,
    timeout: int,
    http_get: Any,
) -> requests.Response:
    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        delay = 1.0 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            time.sleep(delay)
        response = http_get(
            DISCOGS_SEARCH_URL,
            params=params,
            headers={
                "Accept": "application/json",
                "Authorization": f"Discogs token={token}",
                "User-Agent": USER_AGENT,
            },
            timeout=timeout,
        )
        _LAST_REQUEST_AT = time.monotonic()
    return response


def lookup_discogs_release(
    metadata: Mapping[str, Any],
    *,
    token: str = "",
    timeout: int = 12,
    http_get: Any = requests.get,
) -> dict[str, Any]:
    api_token = str(token or os.environ.get("DISCOGS_TOKEN") or "").strip()
    if not api_token:
        return _provider_result({}, status="disabled", reason="DISCOGS_TOKEN is not configured")
    artist = str(metadata.get("album_artist") or metadata.get("artist") or "").strip()
    album = str(metadata.get("album") or "").strip()
    if not artist or not album or artist == "Unknown" or album == "Unknown":
        return _provider_result({}, status="not_applicable", reason="Artist and album are required")
    try:
        response = _rate_limited_get(
            params={
                "type": "release",
                "artist": artist,
                "release_title": album,
                "per_page": 10,
                "page": 1,
            },
            token=api_token,
            timeout=timeout,
            http_get=http_get,
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("results") if isinstance(payload, dict) else []
        for result in candidates or []:
            if isinstance(result, dict) and _exact_release(result, artist, album):
                reference = str(result.get("resource_url") or result.get("uri") or "")
                return _provider_result(
                    parse_discogs_result(result),
                    confidence=0.94,
                    reference=reference,
                )
        return _provider_result(
            {},
            status="not_found",
            reason="No exact artist and album match",
        )
    except Exception as exc:
        LOGGER.warning("Discogs lookup failed for %s - %s: %s", artist, album, exc)
        return _provider_result({}, status="error", reason=type(exc).__name__)
