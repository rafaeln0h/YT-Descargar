"""High-quality square cover retrieval and cross-format embedding helpers."""

from __future__ import annotations

import base64
import io
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import requests
from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover
from mutagen.wave import WAVE
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_COVER_HOSTS = {
    "coverartarchive.org",
    "archive.org",
    "i.ytimg.com",
    "i9.ytimg.com",
    "lh3.googleusercontent.com",
    "cdn-images.dzcdn.net",
    "e-cdns-images.dzcdn.net",
}
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def clean_artist(value: str) -> str:
    text = str(value or "").strip()
    return re.sub(r"\s+(oficial|official)(\s+channel)?\s*$", "", text, flags=re.I).strip()


def clean_album(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\s*\d{4}\s*-\s*", "", text)
    text = re.sub(r"^\s*(album|single|ep)\s*[-:|]\s*", "", text, flags=re.I)
    return text.strip()


def normalized_identity(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def musicbrainz_release_matches(release: dict, artist: str, album: str) -> bool:
    """Accept only an exact normalized release and artist identity."""

    release_title = normalized_identity(release.get("title") or "")
    release_artist = normalized_identity(release.get("artist-credit-phrase") or "")
    wanted_title = normalized_identity(clean_album(album))
    wanted_artist = normalized_identity(clean_artist(artist))
    return bool(
        release_title
        and release_artist
        and release_title == wanted_title
        and release_artist == wanted_artist
    )


def _allowed_cover_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host == allowed or host.endswith("." + allowed)
        for allowed in ALLOWED_COVER_HOSTS
    )


def normalize_cover_bytes(raw: bytes, *, max_size: int = 1600) -> tuple[bytes, int, int]:
    """Decode, orient, center-crop and encode a high-quality square JPEG."""

    if not raw or len(raw) > MAX_DOWNLOAD_BYTES:
        raise ValueError("Imagen de cover vacia o demasiado grande")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Respuesta de cover invalida") from exc

    width, height = image.size
    if width < 120 or height < 120:
        raise ValueError("Cover con resolucion insuficiente")
    side = min(width, height, max_size)
    if width != height or width > max_size:
        image = ImageOps.fit(
            image,
            (side, side),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=94, optimize=True, progressive=True)
    return buffer.getvalue(), image.width, image.height


def download_square_cover(
    url: str,
    *,
    timeout: int = 15,
    http_get=requests.get,
) -> tuple[bytes, int, int]:
    if not _allowed_cover_url(url):
        raise ValueError("Host de cover no permitido")
    response = http_get(
        url,
        timeout=timeout,
        stream=True,
        headers={"User-Agent": "YT-Descargar cover-fetcher"},
    )
    response.raise_for_status()
    final_url = str(getattr(response, "url", url) or url)
    if not _allowed_cover_url(final_url):
        raise ValueError("Redireccion de cover no permitida")
    content_type = str(response.headers.get("Content-Type") or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ValueError("La URL no devolvio una imagen")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(64 * 1024):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_DOWNLOAD_BYTES:
            raise ValueError("Cover remoto demasiado grande")
        chunks.append(chunk)
    return normalize_cover_bytes(b"".join(chunks))


def write_cover(file_path: str | Path, cover_bytes: bytes) -> None:
    """Replace the front cover in common audio containers."""

    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("APIC")
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Front Cover", data=cover_bytes))
        tags.save(path, v2_version=4)
        return

    if suffix in {".m4a", ".mp4"}:
        audio = MP4(path)
        audio["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()
        return

    picture = Picture()
    picture.type = 3
    picture.mime = "image/jpeg"
    picture.desc = "Front Cover"
    picture.data = cover_bytes
    with Image.open(io.BytesIO(cover_bytes)) as image:
        picture.width, picture.height = image.size
        picture.depth = 24

    if suffix == ".flac":
        audio = FLAC(path)
        audio.clear_pictures()
        audio.add_picture(picture)
        audio.save()
        return

    if suffix in {".ogg", ".oga", ".opus"}:
        audio = MutagenFile(path)
        if audio is None:
            raise ValueError("Contenedor Ogg/Opus no reconocido")
        if audio.tags is None:
            audio.add_tags()
        audio["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
        audio.save()
        return

    if suffix == ".wav":
        audio = WAVE(path)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.delall("APIC")
        audio.tags.add(
            APIC(encoding=3, mime="image/jpeg", type=3, desc="Front Cover", data=cover_bytes)
        )
        audio.save()
        return

    raise ValueError(f"El formato {suffix or 'desconocido'} no admite covers")
