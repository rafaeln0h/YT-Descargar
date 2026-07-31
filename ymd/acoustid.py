"""Opt-in acoustic identification using Chromaprint and AcoustID."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Mapping

import requests

LOGGER = logging.getLogger(__name__)
ACOUSTID_LOOKUP_URL = "https://api.acoustid.org/v2/lookup"

_REQUEST_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0


def _provider_result(
    fields: Mapping[str, Any],
    *,
    confidence: float = 0,
    reference: str = "",
    status: str = "ok",
    reason: str = "",
) -> dict[str, Any]:
    return {
        "provider": "acoustid",
        "status": status,
        "fields": {key: value for key, value in dict(fields).items() if value not in ("", None, [])},
        "confidence": round(max(0.0, min(float(confidence), 1.0)), 3),
        "reference": reference,
        "reason": reason,
    }


def resolve_fpcalc(executable: str | Path | None = None) -> str:
    candidate = str(executable or "").strip()
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_file():
            return str(path.resolve())
        return ""
    return shutil.which("fpcalc") or ""


def fingerprint_file(
    audio_path: str | Path,
    *,
    executable: str | Path | None = None,
    timeout: int = 45,
) -> tuple[int, str]:
    path = Path(audio_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("Audio file not found")
    fpcalc = resolve_fpcalc(executable)
    if not fpcalc:
        raise FileNotFoundError("fpcalc/Chromaprint is not installed")
    completed = subprocess.run(
        [fpcalc, "-json", str(path)],
        capture_output=True,
        text=True,
        timeout=max(5, int(timeout)),
        check=True,
        shell=False,
    )
    if len(completed.stdout) > 8 * 1024 * 1024:
        raise ValueError("fpcalc response is unexpectedly large")
    payload = json.loads(completed.stdout)
    duration = max(1, int(round(float(payload.get("duration") or 0))))
    fingerprint = str(payload.get("fingerprint") or "").strip()
    if not fingerprint:
        raise ValueError("fpcalc did not return a fingerprint")
    return duration, fingerprint


def parse_acoustid_payload(payload: Mapping[str, Any], *, minimum_score: float = 0.80) -> dict[str, Any]:
    ranked: list[tuple[float, Mapping[str, Any]]] = []
    for result in payload.get("results") or []:
        if not isinstance(result, dict):
            continue
        try:
            score = float(result.get("score") or 0)
        except (TypeError, ValueError):
            continue
        if score >= minimum_score:
            ranked.append((score, result))
    if not ranked:
        return _provider_result({}, status="not_found", reason="No confident fingerprint match")
    ranked.sort(key=lambda item: item[0], reverse=True)
    score, result = ranked[0]
    recordings = [item for item in result.get("recordings") or [] if isinstance(item, dict)]
    recording = recordings[0] if recordings else {}
    artists = [
        str(item.get("name"))
        for item in recording.get("artists") or []
        if isinstance(item, dict) and item.get("name")
    ]
    release_groups = [item for item in recording.get("releasegroups") or [] if isinstance(item, dict)]
    release_group = release_groups[0] if release_groups else {}
    fields = {
        "acoustid_id": result.get("id", ""),
        "musicbrainz_recordingid": recording.get("id", ""),
        "musicbrainz_releasegroupid": release_group.get("id", ""),
        "title": recording.get("title", ""),
        "artist": "; ".join(artists),
        "album": release_group.get("title", ""),
    }
    return _provider_result(
        fields,
        confidence=score,
        reference=str(result.get("id") or ""),
    )


def _rate_limited_post(
    data: Mapping[str, Any],
    *,
    timeout: int,
    http_post: Any,
) -> requests.Response:
    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        delay = 0.35 - (time.monotonic() - _LAST_REQUEST_AT)
        if delay > 0:
            time.sleep(delay)
        response = http_post(
            ACOUSTID_LOOKUP_URL,
            data=data,
            headers={"Accept": "application/json"},
            timeout=timeout,
        )
        _LAST_REQUEST_AT = time.monotonic()
    return response


def lookup_acoustid_file(
    audio_path: str | Path | None,
    *,
    api_key: str = "",
    fpcalc_path: str | Path | None = None,
    timeout: int = 15,
    http_post: Any = requests.post,
) -> dict[str, Any]:
    key = str(api_key or os.environ.get("ACOUSTID_API_KEY") or "").strip()
    if not key:
        return _provider_result({}, status="disabled", reason="ACOUSTID_API_KEY is not configured")
    if not audio_path:
        return _provider_result({}, status="not_applicable", reason="No audio file was provided")
    if not resolve_fpcalc(fpcalc_path):
        return _provider_result(
            {},
            status="unavailable",
            reason="fpcalc/Chromaprint is not installed",
        )
    try:
        duration, fingerprint = fingerprint_file(
            audio_path,
            executable=fpcalc_path,
            timeout=max(timeout, 30),
        )
        response = _rate_limited_post(
            {
                "client": key,
                "duration": duration,
                "fingerprint": fingerprint,
                "meta": "recordings+releasegroups",
                "format": "json",
            },
            timeout=timeout,
            http_post=http_post,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("status") != "ok":
            return _provider_result({}, status="error", reason="Invalid AcoustID response")
        parsed = parse_acoustid_payload(payload)
        if parsed.get("status") == "ok":
            parsed.setdefault("fields", {})["acoustid_fingerprint"] = fingerprint
        return parsed
    except Exception as exc:
        LOGGER.warning("AcoustID lookup failed: %s", exc)
        return _provider_result(
            {},
            status="error",
            reason=type(exc).__name__,
        )
