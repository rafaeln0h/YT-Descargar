"""Safe GitHub Release discovery for optional client update notices."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

import requests

DEFAULT_REPOSITORY = "rafaeln0h/YT-Descargar"
DEFAULT_CACHE_FILE = Path.home() / ".ymd_update_cache.json"
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def version_parts(value: str) -> tuple[int, ...]:
    """Turn tags such as ``v0.013`` into a numeric tuple for comparison."""

    match = re.search(r"\d+(?:\.\d+)*", str(value or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))


def is_newer_version(candidate: str, current: str) -> bool:
    candidate_parts = version_parts(candidate)
    current_parts = version_parts(current)
    if not candidate_parts or not current_parts:
        return False
    size = max(len(candidate_parts), len(current_parts))
    return candidate_parts + (0,) * (size - len(candidate_parts)) > (
        current_parts + (0,) * (size - len(current_parts))
    )


def _read_cache(cache_file: Path) -> dict[str, Any]:
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_cache(cache_file: Path, payload: dict[str, Any]) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_suffix(cache_file.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(cache_file)
    except OSError:
        # An update check must never prevent the application from starting.
        return


def _release_payload(raw: dict[str, Any]) -> dict[str, Any]:
    tag = str(raw.get("tag_name") or "").strip()
    page = str(raw.get("html_url") or "").strip()
    if page and not page.startswith("https://github.com/"):
        page = ""
    return {
        "tag": tag,
        "name": str(raw.get("name") or tag).strip(),
        "url": page,
        "published_at": str(raw.get("published_at") or "").strip(),
        "notes": str(raw.get("body") or "").strip()[:1200],
    }


def check_latest_release(
    current_version: str,
    *,
    repository: str = DEFAULT_REPOSITORY,
    cache_file: str | Path = DEFAULT_CACHE_FILE,
    interval_hours: int = 12,
    force: bool = False,
    http_get: Callable[..., Any] = requests.get,
) -> dict[str, Any]:
    """Return an update status using GitHub Releases and conditional requests."""

    if not REPOSITORY_PATTERN.fullmatch(repository or ""):
        return {
            "status": "disabled",
            "current_version": current_version,
            "update_available": False,
            "error": "Repositorio de actualizaciones invalido",
        }

    cache_path = Path(cache_file).expanduser()
    cache = _read_cache(cache_path)
    now = int(time.time())
    max_age = max(1, int(interval_hours)) * 3600
    cached_release = cache.get("release") if isinstance(cache.get("release"), dict) else {}

    cache_is_fresh = (
        cache.get("repository") == repository
        and int(cache.get("checked_at") or 0) > 0
        and now - int(cache.get("checked_at") or 0) < max_age
    )
    if not force and cache_is_fresh:
        release = dict(cached_release)
        return {
            "status": "ok" if release else "no_release",
            "source": "cache",
            "repository": repository,
            "current_version": current_version,
            "update_available": is_newer_version(release.get("tag", ""), current_version),
            "latest_release": release or None,
        }

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"YT-Descargar/{current_version}",
    }
    if cache.get("etag"):
        headers["If-None-Match"] = str(cache["etag"])

    try:
        response = http_get(
            f"https://api.github.com/repos/{repository}/releases/latest",
            headers=headers,
            timeout=6,
        )
        if response.status_code == 304 and cached_release:
            release = dict(cached_release)
        elif response.status_code == 200:
            raw = response.json()
            release = _release_payload(raw if isinstance(raw, dict) else {})
            cache["etag"] = response.headers.get("ETag", "")
        elif response.status_code == 404:
            release = {}
        else:
            raise RuntimeError(f"GitHub respondio HTTP {response.status_code}")

        cache.update({"checked_at": now, "repository": repository, "release": release})
        _write_cache(cache_path, cache)
        return {
            "status": "ok" if release else "no_release",
            "source": "github",
            "repository": repository,
            "current_version": current_version,
            "update_available": is_newer_version(release.get("tag", ""), current_version),
            "latest_release": release or None,
        }
    except Exception as exc:
        release = dict(cached_release)
        return {
            "status": "unavailable",
            "source": "stale_cache" if release else "none",
            "repository": repository,
            "current_version": current_version,
            "update_available": is_newer_version(release.get("tag", ""), current_version),
            "latest_release": release or None,
            "error": str(exc),
        }
