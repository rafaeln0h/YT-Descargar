import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import musicbrainzngs
import requests
import yt_dlp
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

from setup_ffmpeg import ensure_ffmpeg
from ymd.cleanup import remove_generated_sidecars
from ymd.enrichment import enrich_with_musicbrainz
from ymd.logging_config import YTDLPLogger, setup_logging
from ymd.lyrics import lookup_lrclib
from ymd.metadata import (
    apply_metadata_defaults,
    merge_ytdlp_metadata,
)
from ymd.metadata import (
    write_lyrics as write_lyrics_tags,
)
from ymd.metadata import (
    write_metadata as write_metadata_tags,
)
from ymd.routes import create_services_blueprint
from ymd.version import VERSION

# Asegurar que FFmpeg este disponible
FFMPEG_PATH = ensure_ffmpeg()

app = Flask(__name__)
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": [
                r"^http://127\.0\.0\.1(?::\d+)?$",
                r"^http://localhost(?::\d+)?$",
                r"^http://\[::1\](?::\d+)?$",
            ]
        }
    },
)

CONFIG_FILE = Path.home() / ".ymd_config.json"
HISTORY_FILE = Path.home() / ".ymd_history.json"
DOWNLOAD_QUEUE = {}
QUEUE_ID = 0
QUEUE_LOCK = threading.Lock()
HISTORY_LOCK = threading.Lock()

APPLICATION_LOG = setup_logging(Path(__file__).resolve().parent / "logs")
LOGGER = logging.getLogger("ymd.app")
musicbrainzngs.set_useragent("YT-Descargar", VERSION)

DEFAULT_CONFIG = {
    'download_path': str(Path.home() / 'Music' / 'YouTube'),
    'archive_file': str(Path.home() / '.ymd_download_archive.txt'),
    'folder_structure': '{artist}/{year} - {album}',
    'filename_format': '{track:02d} - {title}',
    'playlist_folder_mode': 'inherit',
    'playlist_folder_template': '',
    'download_mode': 'audio',
    'audio_format': 'mp3',
    'audio_quality': '320',
    'video_format': 'mp4',
    'video_quality': '1080',
    'download_covers': True,
    'embed_lyrics': True,
    'write_subtitles': False,
    'embed_subtitles': False,
    'playlist_tag_album_mode': 'smart',
    'playlist_tag_artist_mode': 'detected',
    'playlist_tag_album_artist_mode': 'playlist_owner',
    'playlist_track_number_mode': 'album',
    'playlist_tag_genre_mode': 'empty',
    'playlist_default_genre': '',
    'use_download_archive': True,
    'cookies_from_browser': '',
    'cookies_profile': '',
    'youtube_player_client': 'default,web_music',
    'retry_count': 10,
    'fragment_retries': 10,
    'concurrent_fragments': 1,
    'sleep_interval': 0,
    'max_sleep_interval': 0,
    'auto_metadata': True,
    'metadata_sources': ['musicbrainz', 'manual'],
    'embed_extended_metadata': True,
    'duplicate_mode': 'skip',
    'smart_organize': True,
    'ui_render_mode': 'list',
    'ui_albums_only_mode': False,
    'ui_selection_filter': 'all',
    'ui_list_height': 560,
    'ui_item_search': '',
    'ui_display_filter': 'all',
    'library_scan_limit': 300,
    'metadata_defaults': {
        'composer': '',
        'publisher': '',
        'copyright': '',
        'language': '',
        'comment': '',
        'bpm': '',
        'disc': '',
        'disc_total': '',
        'track_total': '',
        'isrc': '',
        'grouping': '',
        'compilation': False,
        'explicit': False,
        'release_type': '',
        'release_country': '',
        'release_status': '',
        'catalog_number': '',
        'barcode': '',
        'mood': '',
    },
}


class QuietYTDLPLogger(YTDLPLogger):
    """Compatibility name for the yt-dlp logging bridge."""


class DownloadCancelled(Exception):
    pass


def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    return loaded
        except Exception:
            return []
    return []


def save_history(items):
    trimmed = list(items)[-200:]
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(trimmed, f, indent=2, ensure_ascii=False)


def add_history_entry(entry):
    with HISTORY_LOCK:
        items = load_history()
        items.append(entry)
        save_history(items)


def update_history_entry(history_id, patch):
    with HISTORY_LOCK:
        items = load_history()
        for item in items:
            if item.get('history_id') == history_id:
                item.update(patch)
                item['updated_at'] = datetime.now().isoformat(timespec='seconds')
                break
        save_history(items)


def get_history_entry(history_id):
    items = load_history()
    for item in items:
        if item.get('history_id') == history_id:
            return item
    return None


def next_queue_id():
    global QUEUE_ID
    with QUEUE_LOCK:
        QUEUE_ID += 1
        return QUEUE_ID


def is_active_queue_status(status):
    return status in {'iniciando', 'analizando', 'descargando', 'pausado'}


def find_active_duplicate_queue(kind, source_url):
    target_kind = (kind or '').strip().lower() or 'single'
    normalized_url = normalize_input_url(source_url)
    for queue in DOWNLOAD_QUEUE.values():
        if (queue.get('type') or '').lower() != target_kind:
            continue
        if not is_active_queue_status(queue.get('status')):
            continue
        if normalize_input_url(queue.get('source_url')) == normalized_url:
            return queue.get('queue_id')
    return None


def update_queue_state(queue_id, patch):
    if queue_id in DOWNLOAD_QUEUE:
        DOWNLOAD_QUEUE[queue_id].update(patch)


def apply_queue_control(queue_id):
    queue = DOWNLOAD_QUEUE.get(queue_id)
    if not queue:
        return
    while queue.get('pause_requested'):
        queue['status'] = 'pausado'
        queue['message'] = 'Descarga en pausa'
        update_history_entry(queue.get('history_id'), {
            'status': 'pausado',
            'progress': queue.get('progress', 0),
            'destination': queue.get('destination'),
        })
        if queue.get('cancel_requested'):
            break
        time.sleep(0.5)

    if queue.get('cancel_requested'):
        queue['status'] = 'cancelado'
        queue['message'] = 'Descarga cancelada por el usuario'
        update_history_entry(queue.get('history_id'), {
            'status': 'cancelado',
            'progress': queue.get('progress', 0),
            'destination': queue.get('destination'),
            'error': 'Cancelado por el usuario',
        })
        raise DownloadCancelled('Cancelado por el usuario')


def create_history_payload(data):
    try:
        return json.loads(json.dumps(data, ensure_ascii=False))
    except Exception:
        return {}


def pick_best_thumbnail(entry):
    if not isinstance(entry, dict):
        return ''

    thumb = entry.get('thumbnail')
    if isinstance(thumb, str) and thumb.strip():
        return thumb.strip()

    thumbs = entry.get('thumbnails') or []
    if isinstance(thumbs, list) and thumbs:
        sorted_thumbs = sorted(
            [t for t in thumbs if isinstance(t, dict) and t.get('url')],
            key=lambda t: (int(t.get('width') or 0) * int(t.get('height') or 0), int(t.get('preference') or 0)),
            reverse=True
        )
        if sorted_thumbs:
            return sorted_thumbs[0].get('url', '')
    return ''


def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    loaded.pop('write_metadata_json', None)
                    merged = dict(DEFAULT_CONFIG)
                    merged.update(loaded)
                    merged['metadata_defaults'] = {
                        **DEFAULT_CONFIG['metadata_defaults'],
                        **(loaded.get('metadata_defaults') or {}),
                    }
                    return merged
    return dict(DEFAULT_CONFIG)


def save_config(config):
    config = dict(config)
    config.pop('write_metadata_json', None)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


app.register_blueprint(
    create_services_blueprint(load_config, log_path=APPLICATION_LOG)
)


def build_runtime_config(request_data):
    config = load_config()
    if not request_data:
        return config

    for key in (
        'download_mode',
        'audio_format',
        'audio_quality',
        'video_format',
        'video_quality',
        'archive_file',
        'cookies_from_browser',
        'cookies_profile',
        'youtube_player_client',
        'playlist_tag_album_mode',
        'playlist_tag_artist_mode',
        'playlist_tag_album_artist_mode',
        'playlist_track_number_mode',
        'playlist_tag_genre_mode',
        'playlist_default_genre',
        'folder_structure',
        'filename_format',
        'playlist_folder_mode',
        'playlist_folder_template',
        'duplicate_mode'
    ):
        value = request_data.get(key)
        if isinstance(value, str) and value.strip():
            config[key] = value.strip()

    for key in (
        'download_covers',
        'auto_metadata',
        'smart_organize',
        'embed_lyrics',
        'write_subtitles',
        'embed_subtitles',
        'use_download_archive',
        'embed_extended_metadata'
    ):
        if key in request_data:
            config[key] = bool(request_data.get(key))

    for key in ('retry_count', 'fragment_retries', 'concurrent_fragments', 'sleep_interval', 'max_sleep_interval'):
        if key in request_data:
            try:
                config[key] = max(0, int(request_data.get(key)))
            except Exception:
                pass

    metadata_defaults = request_data.get('metadata_defaults')
    if isinstance(metadata_defaults, dict):
        allowed_metadata_defaults = DEFAULT_CONFIG['metadata_defaults'].keys()
        current_defaults = dict(config.get('metadata_defaults') or {})
        for key in allowed_metadata_defaults:
            if key in metadata_defaults:
                current_defaults[key] = metadata_defaults[key]
        config['metadata_defaults'] = current_defaults

    # Persistimos para que la UI conserve la ultima configuracion usada.
    save_config(config)

    runtime_config = dict(config)
    runtime_config['force_redownload'] = bool(request_data.get('force_redownload'))
    return runtime_config


def detect_url_type(url):
    """Detecta todos los tipos de URLs de YouTube"""
    normalized = normalize_input_url(url)
    if not normalized:
        return 'unknown'
    parsed = urlparse(normalized)
    path = parsed.path.lower()
    query = parse_qs(parsed.query)

    if 'music.youtube.com' in parsed.netloc.lower():
        if '/playlist' in path or 'list' in query:
            return 'playlist'
        if any(part in path for part in ('/channel/', '/browse/', '/artist/')):
            return 'channel'
        if any(part in path for part in ('/watch', '/shorts/', '/live/', '/embed/', '/v/')) or 'v' in query:
            return 'video'

    if any(host in parsed.netloc.lower() for host in ('youtube.com', 'youtu.be', 'm.youtube.com', 'youtube-nocookie.com')):
        if any(part in path for part in ('/@', '/c/', '/user/', '/channel/', '/videos', '/streams', '/shorts', '/live')):
            return 'channel'
        if '/playlist' in path or 'list' in query:
            return 'playlist'
        if any(part in path for part in ('/mix', '/feed/')) and 'list' in query:
            return 'playlist'
        if any(part in path for part in ('/watch', '/shorts/', '/live/', '/embed/', '/v/')) or 'v' in query or parsed.netloc.lower().endswith('youtu.be'):
            return 'video'

    return 'unknown'


def normalize_input_url(url):
    raw = (url or '').strip()
    if not raw:
        return ''
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return f"https://www.youtube.com/watch?v={raw}"

    if not re.match(r'^https?://', raw, re.IGNORECASE):
        raw = 'https://' + raw.lstrip('/')

    try:
        parsed = urlparse(raw)
    except Exception:
        return raw

    netloc = (parsed.netloc or '').lower()
    path = parsed.path or ''
    query = parse_qs(parsed.query)

    host_map = {
        'youtu.be': 'www.youtube.com',
        'm.youtube.com': 'www.youtube.com',
        'youtube.com': 'www.youtube.com',
        'www.youtube-nocookie.com': 'www.youtube.com',
        'youtube-nocookie.com': 'www.youtube.com',
    }
    netloc = host_map.get(netloc, netloc)

    if netloc == 'www.youtube.com' and path.startswith('/embed/'):
        video_id = path.split('/embed/', 1)[1].split('/', 1)[0]
        if video_id:
            query['v'] = [video_id]
            return urlunparse(('https', netloc, '/watch', '', urlencode(query, doseq=True), ''))

    if netloc == 'www.youtube.com' and path.startswith('/v/'):
        video_id = path.split('/v/', 1)[1].split('/', 1)[0]
        if video_id:
            query['v'] = [video_id]
            return urlunparse(('https', netloc, '/watch', '', urlencode(query, doseq=True), ''))

    if netloc == 'www.youtube.com' and path.startswith('/shorts/'):
        video_id = path.split('/shorts/', 1)[1].split('/', 1)[0]
        if video_id:
            query['v'] = [video_id]
            return urlunparse(('https', netloc, '/watch', '', urlencode(query, doseq=True), ''))

    if netloc == 'www.youtube.com' and path.startswith('/live/'):
        video_id = path.split('/live/', 1)[1].split('/', 1)[0]
        if video_id:
            query['v'] = [video_id]
            return urlunparse(('https', netloc, '/watch', '', urlencode(query, doseq=True), ''))

    if parsed.netloc.lower() == 'youtu.be':
        video_id = path.strip('/').split('/', 1)[0]
        if video_id:
            query['v'] = [video_id]
            return urlunparse(('https', 'www.youtube.com', '/watch', '', urlencode(query, doseq=True), ''))

    if path.startswith('/clip/'):
        return raw

    return urlunparse(('https', netloc or parsed.netloc, path, '', urlencode(query, doseq=True), ''))


def normalize_video_url(entry):
    if not entry:
        return None

    candidate = entry.get('webpage_url') or entry.get('url')
    if not candidate:
        video_id = entry.get('id')
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
        return None

    if isinstance(candidate, str):
        normalized = normalize_input_url(candidate)
        if normalized:
            return normalized
        if candidate.startswith(('http://', 'https://')):
            return candidate
        if candidate.startswith('/playlist'):
            return f"https://music.youtube.com{candidate}"
        if candidate.startswith('/channel') or candidate.startswith('/browse'):
            return f"https://music.youtube.com{candidate}"
        if candidate.startswith('/watch'):
            if 'list=' in candidate:
                return f"https://music.youtube.com{candidate}"
            return f"https://www.youtube.com{candidate}"
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
            return f"https://www.youtube.com/watch?v={candidate}"

    return candidate


def classify_entry_type(url):
    if not url:
        return 'song'
    low = url.lower()
    if '/channel/' in low or '/browse/' in low:
        return 'artist'
    if '/playlist' in low or ('watch' in low and 'list=' in low):
        return 'collection'
    return 'song'


def parse_entries(entries, default_artist='Unknown', limit=100, source='default'):
    parsed = []
    for idx, entry in enumerate(entries[:limit], 1):
        if not entry:
            continue
        normalized = normalize_video_url(entry)
        if not normalized:
            continue
        item_type = classify_entry_type(normalized)
        if item_type == 'artist':
            # Enlaces de secciones/canales no son descargables directos.
            continue
        parsed.append({
            'id': entry.get('id'),
            'title': entry.get('title', f'Track {idx}'),
            'duration': entry.get('duration', 0),
            'artist': entry.get('artist', entry.get('uploader', default_artist)),
            'album': entry.get('album', ''),
            'album_artist': entry.get('album_artist', ''),
            'year': entry.get('release_year') or (entry.get('upload_date') or '')[:4],
            'track': entry.get('track_number', idx),
            'track_total': entry.get('track_count', ''),
            'disc': entry.get('disc_number', ''),
            'disc_total': entry.get('disc_count', ''),
            'genre': (entry.get('genres') or [entry.get('genre', '')])[0],
            'composer': entry.get('composer', ''),
            'description': entry.get('description', ''),
            'channel': entry.get('channel', entry.get('uploader', '')),
            'thumbnail': pick_best_thumbnail(entry),
            'url': normalized,
            'position': idx,
            'item_type': item_type,
            'source': source
        })
    return parsed


def dedupe_items(items):
    seen = set()
    out = []
    for item in items:
        key = normalize_item_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def normalize_item_key(item):
    url = (item.get('url') or '').strip()
    title = (item.get('title') or '').strip().lower()
    artist = (item.get('artist') or '').strip().lower()
    if not url:
        return ('', title, artist)

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    # Para watch URLs ignoramos parametros que no cambian la cancion.
    if parsed.path == '/watch':
        keep = {}
        if 'v' in query:
            keep['v'] = query['v']
        normalized_query = urlencode(keep, doseq=True)
        clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', normalized_query, ''))
        return (clean, title, artist)
    return (url, title, artist)


def extract_browse_id(url):
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split('/') if p]
    if len(parts) >= 2 and parts[0] == 'browse':
        return parts[1]
    return None


def get_text_runs(node):
    if not isinstance(node, dict):
        return ''
    runs = node.get('runs') or []
    parts = []
    for run in runs:
        if isinstance(run, dict):
            text = run.get('text')
            if text:
                parts.append(text)
    if parts:
        return ''.join(parts).strip()
    return (node.get('simpleText') or '').strip()


def find_first_playlist_id(node):
    if isinstance(node, dict):
        if isinstance(node.get('playlistId'), str) and node.get('playlistId'):
            return node['playlistId']
        for value in node.values():
            result = find_first_playlist_id(value)
            if result:
                return result
    elif isinstance(node, list):
        for value in node:
            result = find_first_playlist_id(value)
            if result:
                return result
    return None


def walk_two_row_renderers(node, output):
    if isinstance(node, dict):
        row = node.get('musicTwoRowItemRenderer')
        if isinstance(row, dict):
            output.append(row)
        for value in node.values():
            walk_two_row_renderers(value, output)
    elif isinstance(node, list):
        for value in node:
            walk_two_row_renderers(value, output)


def resolve_music_browse_items(url):
    """
    Fallback para URLs /browse/ cuando yt-dlp no logra resolver.
    Usa endpoint interno de YouTube Music para extraer colecciones reproducibles.
    """
    browse_id = extract_browse_id(url)
    if not browse_id:
        return None

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        )
    }

    try:
        html = requests.get(url, headers=headers, timeout=20).text
        match = re.search(r'ytcfg\.set\((\{.+?\})\);', html)
        if not match:
            return None
        ytcfg = json.loads(match.group(1))
        api_key = ytcfg.get('INNERTUBE_API_KEY')
        client_version = ytcfg.get('INNERTUBE_CLIENT_VERSION')
        if not api_key or not client_version:
            return None

        payload = {
            'context': {
                'client': {
                    'clientName': 'WEB_REMIX',
                    'clientVersion': client_version,
                    'hl': 'es-419',
                    'gl': 'MX',
                    'originalUrl': url,
                }
            },
            'browseId': browse_id,
        }
        endpoint = f'https://music.youtube.com/youtubei/v1/browse?key={api_key}'
        resp = requests.post(
            endpoint,
            headers={**headers, 'Content-Type': 'application/json'},
            json=payload,
            timeout=20
        )
        if resp.status_code != 200:
            return None
        data = resp.json()

        rows = []
        walk_two_row_renderers(data, rows)
        items = []
        for idx, row in enumerate(rows, 1):
            playlist_id = find_first_playlist_id(row)
            if not playlist_id:
                continue
            if not (playlist_id.startswith('OLAK5uy_') or playlist_id.startswith('RDAMPLOLAK5uy_')):
                # Evita IDs que no corresponden a colecciones musicales reproducibles.
                continue
            title = get_text_runs(row.get('title')) or f'Coleccion {idx}'
            subtitle = get_text_runs(row.get('subtitle'))
            artist = subtitle.split(' • ')[0].strip() if subtitle else 'Unknown'
            items.append({
                'id': playlist_id,
                'title': title,
                'artist': artist or 'Unknown',
                'thumbnail': pick_best_thumbnail(row.get('thumbnailRenderer') or row),
                'url': f'https://music.youtube.com/playlist?list={playlist_id}',
                'position': idx,
                'item_type': 'collection',
                'source': 'browse_fallback',
            })

        items = dedupe_items(items)
        if not items:
            return None

        return {
            'title': f'Browse {browse_id}',
            'artist': items[0].get('artist', 'Unknown'),
            'items': items
        }
    except Exception:
        return None


def discover_music_artist_items(url):
    """
    Para links de artista/canal en YouTube Music intentamos descubrir colecciones
    (albumes/singles/playlists) y canciones visibles.
    """
    base = url.rstrip('/')
    candidates = [
        ('main', base),
        ('albums', f"{base}/albums"),
        ('songs', f"{base}/songs"),
        ('videos', f"{base}/videos"),
        ('playlists', f"{base}/playlists"),
    ]

    discovered = []
    title = ''
    artist = 'Unknown'

    for source, candidate in candidates:
        info = extract_url_info(candidate, url_type='channel', timeout=18)
        if not info:
            continue
        title = title or info.get('title') or info.get('uploader') or ''
        artist = info.get('uploader') or info.get('artist') or title or artist
        entries = info.get('entries') or []
        discovered.extend(parse_entries(entries, default_artist=artist, limit=120, source=source))

    discovered = dedupe_items(discovered)
    return {
        'title': title or artist or 'Artist',
        'artist': artist or 'Unknown',
        'items': discovered
    }


def expand_download_items(items):
    """
    Convierte colecciones (album/playlist) en lista de canciones descargables.
    """
    expanded = []
    for raw in items:
        if not raw or not raw.get('url'):
            continue
        url = raw.get('url')
        item_type = raw.get('item_type') or classify_entry_type(url)
        if item_type == 'collection':
            info = extract_url_info(url, url_type='playlist', timeout=20)
            entries = info.get('entries') if info else []
            collection_title = (info or {}).get('title') or raw.get('title') or 'Collection'
            collection_artist = (info or {}).get('uploader') or raw.get('artist') or 'Unknown'
            for idx, entry in enumerate(entries or [], 1):
                if not entry:
                    continue
                song_url = normalize_video_url(entry)
                if not song_url:
                    continue
                expanded.append({
                    'title': entry.get('title', f'Track {idx}'),
                    'artist': entry.get('artist', entry.get('uploader', collection_artist)),
                    'album': entry.get('album') or collection_title,
                    'album_artist': entry.get('album_artist', collection_artist),
                    'year': entry.get('release_year', ''),
                    'track': entry.get('track_number', idx),
                    'track_total': entry.get('track_count', len(entries or [])),
                    'disc': entry.get('disc_number', ''),
                    'disc_total': entry.get('disc_count', ''),
                    'genre': (entry.get('genres') or [entry.get('genre', '')])[0],
                    'composer': entry.get('composer', ''),
                    'thumbnail': pick_best_thumbnail(entry),
                    'url': song_url,
                    'item_type': 'song',
                })
        else:
            expanded.append({
                'title': raw.get('title', 'Track'),
                'artist': raw.get('artist', 'Unknown'),
                'album': raw.get('album', ''),
                'album_artist': raw.get('album_artist', ''),
                'year': raw.get('year', ''),
                'track': raw.get('track', raw.get('position', '')),
                'track_total': raw.get('track_total', ''),
                'disc': raw.get('disc', ''),
                'disc_total': raw.get('disc_total', ''),
                'genre': raw.get('genre', ''),
                'composer': raw.get('composer', ''),
                'thumbnail': raw.get('thumbnail', ''),
                'url': url,
                'item_type': 'song',
            })
    return dedupe_items(expanded)


def extract_url_info(url, url_type=None, timeout=30):
    """Extrae informacion de URL sin colgarse"""
    try:
        normalized_url = normalize_input_url(url)
        config = load_config()
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_audio': False,
            'skip_download': True,
            'socket_timeout': timeout,
            'ignoreerrors': True,
            'playlistend': 200,
            'logger': QuietYTDLPLogger(),
            'retries': int(config.get('retry_count', 10)),
            'fragment_retries': int(config.get('fragment_retries', 10)),
            'file_access_retries': 3,
        }

        parsed = urlparse(normalized_url)
        player_clients = [x.strip() for x in str(config.get('youtube_player_client') or '').split(',') if x.strip()]
        if not player_clients:
            player_clients = ['default', 'web_music'] if 'music.youtube.com' in parsed.netloc.lower() else ['default']

        if 'music.youtube.com' in parsed.netloc.lower():
            ydl_opts['extractor_args'] = {
                'youtube': {
                    'player_client': player_clients
                }
            }
        elif player_clients:
            ydl_opts['extractor_args'] = {
                'youtube': {
                    'player_client': player_clients
                }
            }

        browser = (config.get('cookies_from_browser') or '').strip().lower()
        profile = (config.get('cookies_profile') or '').strip()
        if browser:
            ydl_opts['cookiesfrombrowser'] = (browser, profile or None, None, None)

        if url_type in ('playlist', 'channel'):
            # Mas rapido en listas grandes.
            ydl_opts.update({
                'extract_flat': 'in_playlist',
                'lazy_playlist': True,
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(normalized_url, download=False)
    except Exception as e:
        logging.warning(f"Error extrayendo info: {e}")
        return None


def start_single_download(data, queue_id=None):
    url = (data.get('url') or '').strip()
    if not url:
        raise ValueError('URL requerida')

    allow_duplicate_queue = bool(data.get('allow_duplicate_queue'))
    if not allow_duplicate_queue:
        duplicated_queue_id = find_active_duplicate_queue('single', url)
        if duplicated_queue_id:
            return duplicated_queue_id

    queue_id = queue_id or next_queue_id()
    config = build_runtime_config(data)
    metadata = {
        'artist': (data.get('artist') or 'Unknown').strip() or 'Unknown',
        'title': (data.get('title') or '').strip() or 'Unknown',
        'album': (data.get('album') or 'Unknown').strip() or 'Unknown',
        'year': str(data.get('year', datetime.now().year)),
        'track': int(data.get('track', 1)),
        'genre': (data.get('genre') or '').strip(),
        'album_artist': (data.get('album_artist') or '').strip(),
        'composer': (data.get('composer') or '').strip(),
        'publisher': (data.get('publisher') or '').strip(),
        'copyright': (data.get('copyright') or '').strip(),
        'language': (data.get('language') or '').strip(),
        'comment': (data.get('comment') or '').strip(),
        'bpm': data.get('bpm', ''),
        'disc': data.get('disc', ''),
        'disc_total': data.get('disc_total', ''),
        'track_total': data.get('track_total', ''),
        'isrc': (data.get('isrc') or '').strip(),
        'grouping': (data.get('grouping') or '').strip(),
        'compilation': bool(data.get('compilation')),
        'explicit': bool(data.get('explicit')),
        'release_type': (data.get('release_type') or '').strip(),
        'release_country': (data.get('release_country') or '').strip(),
        'release_status': (data.get('release_status') or '').strip(),
        'catalog_number': (data.get('catalog_number') or '').strip(),
        'barcode': (data.get('barcode') or '').strip(),
        'mood': (data.get('mood') or '').strip(),
    }
    metadata = apply_metadata_defaults(
        metadata,
        {},
        source_url=url,
    )

    if metadata['title'] == 'Unknown':
        info = extract_url_info(url, url_type='video', timeout=10)
        if info:
            metadata = merge_ytdlp_metadata(metadata, info)

    output_path, _ = build_output_paths(metadata, config)
    reuse_history_id = (data.get('reuse_history_id') or '').strip()
    history_id = reuse_history_id or f"h{queue_id}_{int(datetime.now().timestamp())}"
    history_entry = {
        'history_id': history_id,
        'queue_id': queue_id,
        'kind': 'single',
        'title': metadata.get('title', 'Unknown'),
        'artist': metadata.get('artist', 'Unknown'),
        'status': 'iniciando',
        'mode': config.get('download_mode', 'audio'),
        'source_url': url,
        'destination': str(output_path),
        'thumbnail': (data.get('thumbnail') or ''),
        'request_payload': create_history_payload(data),
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'updated_at': datetime.now().isoformat(timespec='seconds'),
    }
    if reuse_history_id and get_history_entry(reuse_history_id):
        update_history_entry(reuse_history_id, history_entry)
    else:
        add_history_entry(history_entry)

    DOWNLOAD_QUEUE[queue_id] = {
        'queue_id': queue_id,
        'history_id': history_id,
        'status': 'iniciando',
        'progress': 0,
        'message': 'Preparando descarga...',
        'type': 'single',
        'title': metadata.get('title', 'Unknown'),
        'artist': metadata.get('artist', 'Unknown'),
        'destination': str(output_path),
        'source_url': url,
        'thumbnail': (data.get('thumbnail') or ''),
        'pause_requested': False,
        'cancel_requested': False,
        'media_files': [],
        'created_at': datetime.now().isoformat(timespec='seconds'),
    }

    thread = threading.Thread(
        target=download_worker,
        args=(queue_id, url, metadata, config),
        daemon=True
    )
    thread.start()
    return queue_id


def start_playlist_download(data, queue_id=None):
    url = (data.get('url') or '').strip()
    videos = data.get('videos', [])
    selected_items = data.get('selected_items') or videos
    album = (data.get('album') or 'Album').strip() or 'Album'
    artist = (data.get('artist') or 'Unknown').strip() or 'Unknown'
    config = build_runtime_config(data)

    if not url and not selected_items:
        raise ValueError('URL o lista de videos requerida')

    allow_duplicate_queue = bool(data.get('allow_duplicate_queue'))
    if url and not allow_duplicate_queue:
        duplicated_queue_id = find_active_duplicate_queue('playlist', url)
        if duplicated_queue_id:
            return duplicated_queue_id

    queue_id = queue_id or next_queue_id()

    reuse_history_id = (data.get('reuse_history_id') or '').strip()
    history_id = reuse_history_id or f"h{queue_id}_{int(datetime.now().timestamp())}"
    history_entry = {
        'history_id': history_id,
        'queue_id': queue_id,
        'kind': 'playlist',
        'title': album,
        'artist': artist,
        'status': 'analizando',
        'mode': config.get('download_mode', 'audio'),
        'source_url': url,
        'destination': str(Path(config['download_path'])),
        'thumbnail': (data.get('thumbnail') or ''),
        'request_payload': create_history_payload(data),
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'updated_at': datetime.now().isoformat(timespec='seconds'),
        'total_items': len(selected_items),
    }
    if reuse_history_id and get_history_entry(reuse_history_id):
        update_history_entry(reuse_history_id, history_entry)
    else:
        add_history_entry(history_entry)

    DOWNLOAD_QUEUE[queue_id] = {
        'queue_id': queue_id,
        'history_id': history_id,
        'status': 'analizando',
        'progress': 0,
        'message': 'Analizando...',
        'type': 'playlist',
        'title': album,
        'artist': artist,
        'destination': str(Path(config['download_path'])),
        'source_url': url,
        'thumbnail': (data.get('thumbnail') or ''),
        'pause_requested': False,
        'cancel_requested': False,
        'media_files': [],
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'total_videos': len(selected_items),
        'downloaded': 0,
        'skipped': 0,
        'replaced': 0
    }

    thread = threading.Thread(
        target=playlist_download_worker,
        args=(queue_id, url, selected_items, artist, album, config),
        daemon=True
    )
    thread.start()
    return queue_id


def resolve_playlist_tags(video, playlist_index, playlist_title, playlist_artist, smart_organize, config, track_by_album):
    detected_artist = (video.get('artist') or '').strip()
    detected_album = (video.get('album') or '').strip()
    album_mode = (config.get('playlist_tag_album_mode') or 'smart').lower()
    artist_mode = (config.get('playlist_tag_artist_mode') or 'detected').lower()
    album_artist_mode = (config.get('playlist_tag_album_artist_mode') or 'playlist_owner').lower()
    track_mode = (config.get('playlist_track_number_mode') or 'album').lower()
    genre_mode = (config.get('playlist_tag_genre_mode') or 'empty').lower()
    default_genre = (config.get('playlist_default_genre') or '').strip()

    if album_mode == 'playlist_title':
        album_name = playlist_title
    elif album_mode == 'detected_album':
        album_name = detected_album or playlist_title
    elif album_mode == 'artist_plus_playlist':
        album_name = f"{playlist_artist} - {playlist_title}".strip(' -')
    else:
        album_name = (detected_album if smart_organize and detected_album else playlist_title) or playlist_title

    if artist_mode == 'playlist_owner':
        artist_name = playlist_artist or detected_artist or 'Unknown'
    elif artist_mode == 'various_artists':
        artist_name = 'Various Artists'
    else:
        artist_name = (detected_artist if smart_organize and detected_artist else playlist_artist) or playlist_artist or 'Unknown'

    if album_artist_mode == 'track_artist':
        album_artist = artist_name
    elif album_artist_mode == 'various_artists':
        album_artist = 'Various Artists'
    elif album_artist_mode == 'none':
        album_artist = ''
    else:
        album_artist = playlist_artist or artist_name

    if track_mode == 'playlist':
        track_number = playlist_index
    else:
        next_album_track = track_by_album.get(album_name, 0) + 1
        track_by_album[album_name] = next_album_track
        track_number = next_album_track

    if genre_mode == 'playlist_title':
        genre_name = playlist_title
    elif genre_mode == 'custom':
        genre_name = default_genre
    else:
        genre_name = ''

    return album_name or playlist_title, artist_name, album_artist, track_number, genre_name


@app.route('/')
def index():
    response = app.make_response(render_template('index_playlist.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/settings')
def settings():
    response = app.make_response(render_template('settings.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/suite')
def suite():
    response = app.make_response(render_template('suite.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/config', methods=['GET', 'POST'])
def get_config():
    if request.method == 'POST':
        payload = request.json or {}
        if not isinstance(payload, dict):
            return jsonify({'error': 'Payload de configuracion invalido'}), 400
        config = dict(DEFAULT_CONFIG)
        config.update(payload)
        if not str(config.get('download_path', '')).strip():
            config['download_path'] = DEFAULT_CONFIG['download_path']
        if not str(config.get('folder_structure', '')).strip():
            config['folder_structure'] = DEFAULT_CONFIG['folder_structure']
        if not str(config.get('filename_format', '')).strip():
            config['filename_format'] = DEFAULT_CONFIG['filename_format']
        save_config(config)
        return jsonify({'status': 'ok', 'config': config})
    return jsonify(load_config())


@app.route('/api/config/reset', methods=['POST'])
def reset_config():
    config = dict(DEFAULT_CONFIG)
    save_config(config)
    return jsonify({'status': 'ok', 'config': config})


@app.route('/api/detect-url', methods=['POST'])
def detect_url():
    try:
        data = request.json or {}
        url = normalize_input_url(data.get('url'))
        force_type = (data.get('force_type') or '').strip().lower()

        if not url:
            return jsonify({'error': 'URL requerida'}), 400

        if '/clip/' in urlparse(url).path.lower():
            return jsonify({
                'error': 'Las URLs de clips no son descargables directamente. Abre el video original y pega la URL del video completo.'
            }), 400

        url_type = detect_url_type(url)
        if force_type in ('video', 'playlist', 'channel', 'artist'):
            url_type = 'channel' if force_type == 'artist' else force_type
            parsed_forced = urlparse(url)
            forced_query = parse_qs(parsed_forced.query)
            if url_type == 'playlist' and forced_query.get('list'):
                playlist_id = forced_query['list'][0]
                host = 'music.youtube.com' if 'music.youtube.com' in parsed_forced.netloc.lower() else 'www.youtube.com'
                url = f"https://{host}/playlist?list={playlist_id}"
            elif url_type == 'video' and forced_query.get('v'):
                video_id = forced_query['v'][0]
                host = 'music.youtube.com' if 'music.youtube.com' in parsed_forced.netloc.lower() else 'www.youtube.com'
                url = f"https://{host}/watch?v={video_id}"
        if url_type == 'unknown':
            return jsonify({
                'error': 'URL no valida. Usa links de YouTube o YouTube Music',
                'examples': [
                    'https://music.youtube.com/playlist?list=...',
                    'https://www.youtube.com/playlist?list=...',
                    'https://www.youtube.com/watch?v=...'
                ]
            }), 400

        url_lower = url.lower()
        is_music_browse = 'music.youtube.com' in url_lower and '/browse/' in urlparse(url).path

        info = extract_url_info(url, url_type=url_type, timeout=15)
        browse_fallback = None
        if is_music_browse and info is None:
            browse_fallback = resolve_music_browse_items(url)
            if browse_fallback:
                items = browse_fallback.get('items', [])
                return jsonify({
                    'type': 'artist',
                    'normalized_url': url,
                    'title': browse_fallback.get('title', 'Artist'),
                    'uploader': browse_fallback.get('artist', 'Unknown'),
                    'thumbnail': (items[0].get('thumbnail') if items else ''),
                    'total_videos': len(items),
                    'videos': items,
                    'collections': len([x for x in items if x.get('item_type') == 'collection']),
                    'songs': len([x for x in items if x.get('item_type') == 'song']),
                })

        if info is None:
            return jsonify({
                'error': 'No se pudo obtener informacion. Verifica la URL.',
                'url_type': url_type
            }), 500

        if url_type == 'playlist' and 'entries' in info:
            videos = parse_entries(
                info.get('entries', []),
                default_artist=info.get('uploader', 'Unknown'),
                limit=200,
                source='playlist'
            )

            return jsonify({
                'type': 'playlist',
                'normalized_url': url,
                'title': info.get('title', 'Playlist'),
                'uploader': info.get('uploader', 'Unknown'),
                'thumbnail': pick_best_thumbnail(info),
                'total_videos': len(info.get('entries', [])),
                'videos': [v for v in videos if v.get('url')],
                'description': (info.get('description') or '')[:200]
            })

        if url_type == 'channel':
            is_music_channel = 'music.youtube.com' in url_lower
            if is_music_channel:
                artist_data = discover_music_artist_items(url)
                items = artist_data.get('items', [])
                if not items and is_music_browse:
                    browse_fallback = browse_fallback or resolve_music_browse_items(url)
                    if browse_fallback:
                        items = browse_fallback.get('items', [])
                        artist_data = {
                            'title': browse_fallback.get('title', 'Artist'),
                            'artist': browse_fallback.get('artist', 'Unknown'),
                            'items': items
                        }
                return jsonify({
                    'type': 'artist',
                    'normalized_url': url,
                    'title': artist_data.get('title', 'Artist'),
                    'uploader': artist_data.get('artist', 'Unknown'),
                    'thumbnail': (items[0].get('thumbnail') if items else ''),
                    'total_videos': len(items),
                    'videos': items,
                    'collections': len([x for x in items if x.get('item_type') == 'collection']),
                    'songs': len([x for x in items if x.get('item_type') == 'song']),
                })

            videos = parse_entries(
                info.get('entries', []),
                default_artist=info.get('uploader', 'Unknown'),
                limit=200,
                source='channel'
            )

            return jsonify({
                'type': 'channel',
                'normalized_url': url,
                'title': info.get('uploader', 'Channel'),
                'thumbnail': pick_best_thumbnail(info),
                'total_videos': len(info.get('entries', [])),
                'videos': [v for v in videos if v.get('url')]
            })

        return jsonify({
            'type': 'video',
            'normalized_url': url,
            'title': info.get('title', 'Video'),
            'artist': info.get('artist', info.get('uploader', 'Unknown')),
            'album': info.get('album', ''),
            'thumbnail': pick_best_thumbnail(info),
            'duration': info.get('duration', 0),
            'description': (info.get('description') or '')[:200]
        })

    except Exception as e:
        return jsonify({'error': f'Error: {str(e)}'}), 500


@app.route('/api/download-single', methods=['POST'])
def download_single():
    try:
        data = request.json or {}
        data['url'] = normalize_input_url(data.get('url'))
        existing_queue_id = find_active_duplicate_queue('single', data.get('url'))
        queue_id = start_single_download(data)
        duplicated = bool(existing_queue_id and existing_queue_id == queue_id)
        return jsonify({
            'queue_id': queue_id,
            'duplicate': duplicated,
            'message': ('Ya existe una descarga activa para esa URL; se reutilizo la cola existente.' if duplicated else '')
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download-playlist', methods=['POST'])
def download_playlist():
    try:
        data = request.json or {}
        data['url'] = normalize_input_url(data.get('url'))
        existing_queue_id = find_active_duplicate_queue('playlist', data.get('url'))
        queue_id = start_playlist_download(data)
        duplicated = bool(existing_queue_id and existing_queue_id == queue_id)
        return jsonify({
            'queue_id': queue_id,
            'duplicate': duplicated,
            'message': ('Ya existe una descarga activa para esa URL; se reutilizo la cola existente.' if duplicated else '')
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def playlist_download_worker(queue_id, url, selected_items, artist, album, config):
    try:
        apply_queue_control(queue_id)
        items = selected_items or []
        if not items and url:
            info = extract_url_info(url, url_type='playlist', timeout=20)
            entries = info.get('entries', []) if info else []
            items = [
                {'title': entry.get('title', 'Track'), 'url': normalize_video_url(entry)}
                for entry in entries if entry
            ]

        videos = expand_download_items(items)
        total = len(videos)
        if total == 0:
            raise RuntimeError('No se encontraron videos descargables en la playlist/canal.')

        DOWNLOAD_QUEUE[queue_id]['total_videos'] = total
        update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
            'status': 'descargando',
            'total_items': total,
        })
        smart_organize = bool(config.get('smart_organize', True))
        skipped = 0
        replaced = 0
        downloaded = 0
        failed = 0
        failed_items = []
        track_by_album = {}
        playlist_title = album or 'Playlist'
        playlist_artist = artist or 'Unknown'

        pending_attempts = [{'video': video, 'idx': idx, 'attempt': 1} for idx, video in enumerate(videos, 1)]
        max_item_attempts = 2  # intento inicial + 1 reintento al final
        attempted_slots = set()

        while pending_attempts:
            task = pending_attempts.pop(0)
            video = task.get('video') or {}
            idx = int(task.get('idx') or 0)
            attempt = int(task.get('attempt') or 1)
            slot_key = (idx, attempt)
            if slot_key in attempted_slots:
                continue
            attempted_slots.add(slot_key)

            apply_queue_control(queue_id)
            if not video or not video.get('url'):
                continue

            album_name, artist_name, album_artist, track_number, genre_name = resolve_playlist_tags(
                video,
                idx,
                playlist_title,
                playlist_artist,
                smart_organize,
                config,
                track_by_album
            )

            metadata = {
                'artist': artist_name,
                'title': video.get('title', f'Track {idx}'),
                'album': album_name,
                'album_artist': video.get('album_artist') or album_artist,
                'year': str(video.get('year') or datetime.now().year),
                'track': video.get('track') or track_number,
                'track_total': video.get('track_total') or total,
                'disc': video.get('disc', ''),
                'disc_total': video.get('disc_total', ''),
                'genre': video.get('genre') or genre_name,
                'composer': video.get('composer', ''),
                'playlist_title': playlist_title,
                'playlist_owner': playlist_artist,
                'playlist_track': idx,
                'playlist_total': total,
                'is_playlist_item': True
            }
            metadata = apply_metadata_defaults(
                metadata,
                {},
                source_url=video.get('url', ''),
            )

            try:
                result = download_worker(
                    queue_id,
                    video.get('url'),
                    metadata,
                    config,
                    is_playlist=True,
                    current=idx,
                    total=total
                )
                if result == 'skipped':
                    skipped += 1
                elif result == 'replaced':
                    replaced += 1
                    downloaded += 1
                elif result == 'downloaded':
                    downloaded += 1
            except DownloadCancelled:
                raise
            except Exception as item_error:
                logging.warning(f"Fallo item playlist {idx} (intento {attempt}/{max_item_attempts}): {item_error}")
                if attempt < max_item_attempts:
                    pending_attempts.append({'video': video, 'idx': idx, 'attempt': attempt + 1})
                else:
                    failed += 1
                    failed_items.append({
                        'index': idx,
                        'title': video.get('title', f'Track {idx}'),
                        'url': video.get('url', ''),
                        'error': str(item_error),
                    })

            DOWNLOAD_QUEUE[queue_id]['downloaded'] = downloaded
            DOWNLOAD_QUEUE[queue_id]['skipped'] = skipped
            DOWNLOAD_QUEUE[queue_id]['replaced'] = replaced
            DOWNLOAD_QUEUE[queue_id]['failed'] = failed
            DOWNLOAD_QUEUE[queue_id]['failed_items'] = failed_items[-30:]
            if attempt > 1:
                DOWNLOAD_QUEUE[queue_id]['message'] = f'Reintentando item {idx}/{total} ({attempt}/{max_item_attempts})...'
            else:
                DOWNLOAD_QUEUE[queue_id]['message'] = f'Descargando {idx}/{total}...'
            DOWNLOAD_QUEUE[queue_id]['progress'] = int((idx / total) * 100)
            update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
                'status': 'descargando',
                'progress': DOWNLOAD_QUEUE[queue_id]['progress'],
                'downloaded': downloaded,
                'skipped': skipped,
                'replaced': replaced,
                'failed': failed,
                'destination': DOWNLOAD_QUEUE[queue_id].get('destination'),
            })

        DOWNLOAD_QUEUE[queue_id]['progress'] = 100
        DOWNLOAD_QUEUE[queue_id]['skipped'] = skipped
        DOWNLOAD_QUEUE[queue_id]['replaced'] = replaced
        DOWNLOAD_QUEUE[queue_id]['failed'] = failed
        DOWNLOAD_QUEUE[queue_id]['failed_items'] = failed_items[-30:]

        if downloaded > 0 or skipped > 0 or replaced > 0:
            DOWNLOAD_QUEUE[queue_id]['status'] = 'completado'
            if failed > 0:
                DOWNLOAD_QUEUE[queue_id]['message'] = f'Completado con faltantes: {downloaded} descargadas, {failed} fallidas'
            else:
                DOWNLOAD_QUEUE[queue_id]['message'] = f'OK: {downloaded} canciones descargadas'
            update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
                'status': 'completado',
                'progress': 100,
                'downloaded': downloaded,
                'skipped': skipped,
                'replaced': replaced,
                'failed': failed,
                'failed_items': failed_items[-30:],
                'destination': DOWNLOAD_QUEUE[queue_id].get('destination'),
                'note': ('Completado con algunos errores en items puntuales.' if failed > 0 else ''),
            })
        else:
            DOWNLOAD_QUEUE[queue_id]['status'] = 'error'
            DOWNLOAD_QUEUE[queue_id]['message'] = 'No se pudo descargar ningun item de la playlist'
            update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
                'status': 'error',
                'progress': 100,
                'downloaded': 0,
                'skipped': skipped,
                'replaced': replaced,
                'failed': failed,
                'failed_items': failed_items[-30:],
                'destination': DOWNLOAD_QUEUE[queue_id].get('destination'),
                'error': 'Todos los items fallaron',
            })

    except DownloadCancelled as e:
        DOWNLOAD_QUEUE[queue_id]['status'] = 'cancelado'
        DOWNLOAD_QUEUE[queue_id]['message'] = str(e)
        update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
            'status': 'cancelado',
            'error': str(e),
            'progress': DOWNLOAD_QUEUE[queue_id].get('progress', 0),
        })
    except Exception as e:
        DOWNLOAD_QUEUE[queue_id]['status'] = 'error'
        DOWNLOAD_QUEUE[queue_id]['message'] = str(e)
        update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
            'status': 'error',
            'error': str(e),
            'progress': DOWNLOAD_QUEUE[queue_id].get('progress', 0),
        })


def build_output_paths(metadata, config):
    download_path = Path(config['download_path'])
    download_path.mkdir(parents=True, exist_ok=True)

    safe_metadata = {k: sanitize_component(v) for k, v in metadata.items()}
    safe_metadata['track'] = int(metadata.get('track', 1))
    safe_metadata['playlist_track'] = int(metadata.get('playlist_track', 1))

    is_playlist_item = bool(metadata.get('is_playlist_item'))
    folder_template = resolve_folder_template(config, is_playlist_item)
    folder_structure = safe_format(
        folder_template,
        safe_metadata,
        default=f"{safe_metadata.get('artist', 'Unknown')}/{safe_metadata.get('year', datetime.now().year)} - {safe_metadata.get('album', 'Unknown')}"
    )
    output_path = download_path / folder_structure
    output_path.mkdir(parents=True, exist_ok=True)

    filename_format = safe_format(
        config['filename_format'],
        safe_metadata,
        default=f"{int(safe_metadata.get('track', 1)):02d} - {safe_metadata.get('title', 'Track')}"
    )
    return output_path, filename_format


def resolve_folder_template(config, is_playlist_item=False):
    base_template = (config.get('folder_structure') or '').strip() or '{artist}/{year} - {album}'
    if not is_playlist_item:
        return base_template

    mode = (config.get('playlist_folder_mode') or 'inherit').strip().lower()
    custom_template = (config.get('playlist_folder_template') or '').strip()
    playlist_presets = {
        'inherit': base_template,
        'one_folder': 'Playlists/{playlist_title}',
        'playlist_artist_album': 'Playlists/{playlist_title}/{artist}/{year} - {album}',
        'playlist_album': 'Playlists/{playlist_title}/{album_artist}/{year} - {album}',
        'by_artist': '{artist}/{year} - {album}',
        'by_album': '{album_artist}/{year} - {album}',
        'owner_playlist_artist': '{playlist_owner}/{playlist_title}/{artist}/{year} - {album}',
    }

    if mode == 'custom':
        return custom_template or base_template
    return playlist_presets.get(mode, base_template)


def safe_format(template, metadata, default='Unknown'):
    try:
        return template.format(**metadata)
    except Exception:
        # Fallback seguro si la plantilla tiene placeholders invalidos.
        return default


def sanitize_component(value):
    text = str(value or '').strip()
    if not text:
        return 'Unknown'
    text = re.sub(r'[<>:\"/\\\\|?*]', '_', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text.strip('.')
    return text[:180] if text else 'Unknown'


def subtitle_sort_key(path):
    """
    Prioriza español y luego inglés para elegir la mejor pista de subtítulos.
    """
    name = path.name.lower()
    if '.es' in name:
        return 0
    if '.en' in name:
        return 1
    return 2


def normalize_lyrics_text(text):
    lines = []
    prev = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # ignora timestamps/cabeceras de VTT/SRT
        if line.startswith('WEBVTT') or line.startswith('NOTE'):
            continue
        if re.match(r'^\d+$', line):
            continue
        if re.match(r'^\d{1,2}:\d{2}:\d{2}[.,]\d{3}\s+-->\s+\d{1,2}:\d{2}:\d{2}[.,]\d{3}', line):
            continue
        if re.match(r'^\d{1,2}:\d{2}[.,]\d{3}\s+-->\s+\d{1,2}:\d{2}[.,]\d{3}', line):
            continue
        # quita tags html/vtt
        line = re.sub(r'<[^>]+>', '', line).strip()
        if not line:
            continue
        # evita repeticiones consecutivas
        if line == prev:
            continue
        lines.append(line)
        prev = line
    return '\n'.join(lines).strip()


def extract_lyrics_from_subtitle_file(subtitle_path):
    try:
        raw = subtitle_path.read_text(encoding='utf-8', errors='ignore')
        return normalize_lyrics_text(raw)
    except Exception:
        return ''


def pick_caption_track(info):
    """
    Elige la mejor pista de captions/subtitles disponible para letras.
    """
    if not isinstance(info, dict):
        return None

    language_priority = ['es', 'es-419', 'es-mx', 'en', 'en-us']
    ext_priority = ['vtt', 'srv3', 'ttml', 'srt']
    caption_sets = [
        info.get('subtitles') or {},
        info.get('automatic_captions') or {},
    ]

    for captions in caption_sets:
        if not isinstance(captions, dict):
            continue
        keys = list(captions.keys())
        # prioriza idiomas específicos
        ordered_langs = []
        for pref in language_priority:
            ordered_langs.extend([k for k in keys if k.lower() == pref or k.lower().startswith(pref + '-')])
        ordered_langs.extend([k for k in keys if k not in ordered_langs])

        for lang in ordered_langs:
            tracks = captions.get(lang) or []
            if not isinstance(tracks, list):
                continue
            # prioriza formato texto
            ordered_tracks = sorted(
                tracks,
                key=lambda t: ext_priority.index((t.get('ext') or '').lower())
                if (t.get('ext') or '').lower() in ext_priority else 99
            )
            for track in ordered_tracks:
                url = track.get('url')
                ext = (track.get('ext') or '').lower()
                if url and ext in ext_priority:
                    return {'url': url, 'ext': ext, 'lang': lang}
    return None


def fetch_lyrics_from_youtube(url, info=None):
    """
    Descarga letras/subtítulos como best-effort.
    Nunca debe lanzar excepción para no romper la descarga principal.
    """
    try:
        info = info or extract_url_info(url, url_type='video', timeout=18)
        if not info:
            return '', 'und'
        track = pick_caption_track(info)
        if not track:
            return '', 'und'
        response = requests.get(track['url'], timeout=18)
        if response.status_code != 200:
            return '', 'und'
        text = response.text
        lyrics = normalize_lyrics_text(text)
        lang = track.get('lang', 'und')
        return lyrics, lang
    except Exception:
        return '', 'und'


def apply_lyrics_tag(file_path, lyrics_text, lang='spa', source='', source_id=''):
    return write_lyrics_tags(
        file_path,
        lyrics_text,
        language=lang,
        source=source,
        source_id=source_id,
    )


def download_worker(queue_id, url, metadata, config, is_playlist=False, current=0, total=0):
    output_path = Path(config.get('download_path', Path.home()))
    try:
        apply_queue_control(queue_id)
        output_path, filename_format = build_output_paths(metadata, config)
        if queue_id in DOWNLOAD_QUEUE:
            DOWNLOAD_QUEUE[queue_id]['destination'] = str(output_path)
        duplicate_mode = (config.get('duplicate_mode') or 'skip').lower()
        existing_files = list(output_path.glob(f"{filename_format}.*"))
        replaced_existing = False

        if existing_files and duplicate_mode == 'skip':
            if not is_playlist:
                DOWNLOAD_QUEUE[queue_id]['status'] = 'completado'
                DOWNLOAD_QUEUE[queue_id]['progress'] = 100
                DOWNLOAD_QUEUE[queue_id]['message'] = 'Omitido (archivo ya existe)'
                update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
                    'status': 'completado',
                    'progress': 100,
                    'destination': str(output_path),
                    'note': 'Omitido (archivo ya existe)',
                })
            return 'skipped'
        if existing_files and duplicate_mode == 'replace':
            for file_path in existing_files:
                try:
                    file_path.unlink(missing_ok=True)
                except Exception:
                    pass
            replaced_existing = True
        elif existing_files and duplicate_mode == 'keep':
            # Conserva ambos: agrega sufijo incremental al nombre.
            index = 2
            base_name = filename_format
            while list(output_path.glob(f"{base_name} ({index}).*")):
                index += 1
            filename_format = f"{base_name} ({index})"

        output_template = str(output_path / filename_format)

        download_mode = (config.get('download_mode') or 'audio').lower()
        video_quality = str(config.get('video_quality') or '1080').strip()
        video_format = (config.get('video_format') or 'mp4').lower().strip()
        write_subtitles = bool(config.get('write_subtitles'))
        embed_subtitles = bool(config.get('embed_subtitles'))
        browser = (config.get('cookies_from_browser') or '').strip().lower()
        profile = (config.get('cookies_profile') or '').strip()
        retry_count = int(config.get('retry_count', 10))
        fragment_retries = int(config.get('fragment_retries', 10))
        concurrent_fragments = max(1, int(config.get('concurrent_fragments', 1)))
        sleep_interval = int(config.get('sleep_interval', 0))
        max_sleep_interval = int(config.get('max_sleep_interval', 0))
        archive_file = Path(config.get('archive_file') or (Path.home() / '.ymd_download_archive.txt'))
        force_redownload = bool(config.get('force_redownload'))
        player_clients = [x.strip() for x in str(config.get('youtube_player_client') or '').split(',') if x.strip()]
        if not player_clients:
            player_clients = ['default', 'web_music'] if 'music.youtube.com' in url.lower() else ['default']

        ydl_opts = {
            'writethumbnail': True,
            'outtmpl': output_template,
            'quiet': False,
            'noplaylist': True,
            'retries': retry_count,
            'fragment_retries': fragment_retries,
            'file_access_retries': 3,
            'concurrent_fragment_downloads': concurrent_fragments,
            'progress_hooks': [lambda d: update_progress(queue_id, d, is_playlist, current, total)],
            'extractor_args': {
                'youtube': {
                    'player_client': player_clients
                }
            },
        }

        if sleep_interval > 0:
            ydl_opts['sleep_interval'] = sleep_interval
        if max_sleep_interval > 0:
            ydl_opts['max_sleep_interval'] = max_sleep_interval
        if retry_count > 0 or fragment_retries > 0:
            ydl_opts['retry_sleep_functions'] = {
                'http': lambda _: max(1, sleep_interval or 2),
                'fragment': lambda _: max(1, sleep_interval or 2),
                'extractor': lambda _: max(1, sleep_interval or 2),
                'file_access': lambda _: 1,
            }
        if browser:
            ydl_opts['cookiesfrombrowser'] = (browser, profile or None, None, None)
        if config.get('use_download_archive', True) and not force_redownload:
            archive_file.parent.mkdir(parents=True, exist_ok=True)
            ydl_opts['download_archive'] = str(archive_file)

        if download_mode == 'video':
            max_height = ''.join(ch for ch in video_quality if ch.isdigit()) or '1080'
            if video_format == 'mkv':
                format_selector = (
                    f"bestvideo*[height<={max_height}]+bestaudio/"
                    f"best[height<={max_height}]/best"
                )
            else:
                format_selector = (
                    f"bestvideo*[ext=mp4][height<={max_height}]+bestaudio[ext=m4a]/"
                    f"best[ext=mp4][height<={max_height}]/"
                    f"bestvideo*[height<={max_height}]+bestaudio/"
                    f"best[height<={max_height}]/best"
                )

            postprocessors = []
            if video_format in ('mp4', 'mkv'):
                postprocessors.append({
                    'key': 'FFmpegVideoRemuxer',
                    'preferedformat': video_format,
                })
            if write_subtitles or embed_subtitles:
                ydl_opts['writesubtitles'] = True
                ydl_opts['writeautomaticsub'] = True
                ydl_opts['subtitleslangs'] = ['es', 'en', 'es-*', 'en-*']
                ydl_opts['subtitlesformat'] = 'best'
            if embed_subtitles:
                postprocessors.append({'key': 'FFmpegEmbedSubtitle'})

            ydl_opts.update({
                'format': format_selector,
                'merge_output_format': video_format,
                'postprocessors': postprocessors,
            })
        else:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': config['audio_format'],
                    'preferredquality': config['audio_quality'],
                }, {
                    'key': 'FFmpegThumbnailsConvertor',
                    'format': 'jpg',
                }, {
                    'key': 'EmbedThumbnail',
                }],
            })

        if FFMPEG_PATH:
            ydl_opts['ffmpeg_location'] = FFMPEG_PATH

        max_attempts = 3
        download_info = {}
        for attempt in range(1, max_attempts + 1):
            try:
                apply_queue_control(queue_id)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    download_info = ydl.extract_info(url, download=True) or {}
                break
            except Exception:
                if attempt < max_attempts:
                    DOWNLOAD_QUEUE[queue_id]['message'] = f'Reintentando ({attempt}/{max_attempts - 1})...'
                else:
                    raise

        media_extensions = {
            '.mp3', '.m4a', '.mp4', '.mkv', '.webm', '.flac',
            '.ogg', '.oga', '.opus', '.wav', '.aac'
        }
        downloaded_files = sorted(
            (
                path for path in output_path.glob(f"{filename_format}.*")
                if path.suffix.lower() in media_extensions
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if downloaded_files:
            media_file_path = downloaded_files[0]
            if config.get('embed_extended_metadata', True):
                metadata = merge_ytdlp_metadata(metadata, download_info)
            if (
                download_mode != 'video'
                and config.get('auto_metadata', True)
                and 'musicbrainz' in config.get('metadata_sources', [])
            ):
                metadata = enrich_with_musicbrainz(metadata)
            metadata = apply_metadata_defaults(
                metadata,
                config.get('metadata_defaults'),
                source_url=url,
            )

            if download_mode != 'video' or media_file_path.suffix.lower() == '.mp4':
                apply_metadata(str(media_file_path), metadata)

        if downloaded_files and download_mode != 'video':
            audio_file = downloaded_files[0]

            if config.get('download_covers'):
                download_and_apply_cover(str(audio_file), metadata)

            if config.get('embed_lyrics', True):
                # 1) intenta captions directos de YouTube sin romper la descarga principal
                lyrics_text, lang = fetch_lyrics_from_youtube(url, download_info)
                if lyrics_text:
                    try:
                        tag_lang = 'spa' if str(lang).lower().startswith('es') else 'eng'
                        if apply_lyrics_tag(
                            str(audio_file),
                            lyrics_text,
                            lang=tag_lang,
                            source='youtube_captions',
                            source_id=str(metadata.get('youtube_id') or ''),
                        ):
                            LOGGER.info("Letra incrustada en %s (%s)", audio_file.name, tag_lang)
                    except Exception as exc:
                        LOGGER.warning("No se pudo incrustar la letra en %s: %s", audio_file.name, exc)
                else:
                    # 2) fallback a archivos locales de subtítulos si existen
                    subtitle_candidates = sorted(
                        list(output_path.glob(f"{filename_format}*.vtt")) +
                        list(output_path.glob(f"{filename_format}*.srt")),
                        key=subtitle_sort_key
                    )
                    for sub_file in subtitle_candidates:
                        parsed = extract_lyrics_from_subtitle_file(sub_file)
                        if parsed:
                            try:
                                tag_lang = 'spa' if '.es' in sub_file.name.lower() else 'eng'
                                apply_lyrics_tag(str(audio_file), parsed, lang=tag_lang)
                                break
                            except Exception:
                                continue
                    else:
                        lrclib_match = lookup_lrclib(
                            str(metadata.get('artist') or ''),
                            str(metadata.get('title') or ''),
                            str(metadata.get('album') or ''),
                            metadata.get('duration') or 0,
                        )
                        lrclib_lyrics = str(lrclib_match.get('lyrics') or '')
                        if lrclib_lyrics:
                            try:
                                apply_lyrics_tag(
                                    str(audio_file),
                                    lrclib_lyrics,
                                    lang='und',
                                    source='lrclib',
                                    source_id=str(lrclib_match.get('lrclib_id') or ''),
                                )
                                LOGGER.info("Letra LRCLIB incrustada en %s", audio_file.name)
                            except Exception as exc:
                                LOGGER.warning(
                                    "No se pudo incrustar la letra LRCLIB en %s: %s",
                                    audio_file.name,
                                    exc,
                                )

        if downloaded_files:
            media_file = str(downloaded_files[0].resolve())
            if queue_id in DOWNLOAD_QUEUE:
                media_files = DOWNLOAD_QUEUE[queue_id].setdefault('media_files', [])
                if media_file not in media_files:
                    media_files.append(media_file)
                update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
                    'last_media_file': media_file,
                    'media_files': media_files[-100:],
                })

        if not is_playlist:
            DOWNLOAD_QUEUE[queue_id]['status'] = 'completado'
            DOWNLOAD_QUEUE[queue_id]['progress'] = 100
            DOWNLOAD_QUEUE[queue_id]['message'] = 'Descarga completada'
            update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
                'status': 'completado',
                'progress': 100,
                'destination': str(output_path),
            })
        return 'replaced' if replaced_existing else 'downloaded'

    except DownloadCancelled as e:
        if not is_playlist:
            DOWNLOAD_QUEUE[queue_id]['status'] = 'cancelado'
            DOWNLOAD_QUEUE[queue_id]['message'] = str(e)
            update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
                'status': 'cancelado',
                'progress': DOWNLOAD_QUEUE[queue_id].get('progress', 0),
                'destination': str(output_path),
                'error': str(e),
            })
        else:
            raise
        return 'cancelled'
    except Exception as e:
        if not is_playlist:
            DOWNLOAD_QUEUE[queue_id]['status'] = 'error'
            DOWNLOAD_QUEUE[queue_id]['message'] = str(e)
            update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
                'status': 'error',
                'progress': DOWNLOAD_QUEUE[queue_id].get('progress', 0),
                'destination': str(output_path),
                'error': str(e),
            })
        else:
            raise
        return 'error'


def update_progress(queue_id, d, is_playlist=False, current=0, total=0):
    if queue_id in DOWNLOAD_QUEUE:
        apply_queue_control(queue_id)
    if d.get('status') == 'downloading':
        try:
            raw_percent = d.get('_percent_str', '0%')
            speed = (d.get('_speed_str') or '').strip()
            eta = d.get('_eta_str') or d.get('eta')
            match = re.search(r'(\d+(?:\.\d+)?)', raw_percent)
            progress = int(float(match.group(1))) if match else 0

            if is_playlist and total > 0:
                overall_progress = int(((current - 1 + progress / 100) / total) * 100)
                if DOWNLOAD_QUEUE[queue_id].get('status') != 'pausado':
                    DOWNLOAD_QUEUE[queue_id]['status'] = 'descargando'
                    DOWNLOAD_QUEUE[queue_id]['progress'] = overall_progress
                    DOWNLOAD_QUEUE[queue_id]['message'] = f'Descargando {current}/{total}...'
            else:
                if DOWNLOAD_QUEUE[queue_id].get('status') != 'pausado':
                    DOWNLOAD_QUEUE[queue_id]['status'] = 'descargando'
                    DOWNLOAD_QUEUE[queue_id]['progress'] = progress
                    DOWNLOAD_QUEUE[queue_id]['message'] = 'Descargando...'
            DOWNLOAD_QUEUE[queue_id]['speed'] = speed
            DOWNLOAD_QUEUE[queue_id]['eta'] = str(eta) if eta is not None else ''
            if queue_id in DOWNLOAD_QUEUE:
                update_history_entry(DOWNLOAD_QUEUE[queue_id].get('history_id'), {
                    'status': DOWNLOAD_QUEUE[queue_id].get('status'),
                    'progress': DOWNLOAD_QUEUE[queue_id].get('progress', progress),
                    'destination': DOWNLOAD_QUEUE[queue_id].get('destination'),
                    'speed': speed,
                    'eta': str(eta) if eta is not None else '',
                })
        except Exception:
            pass


def apply_metadata(file_path, metadata):
    try:
        write_metadata_tags(file_path, metadata)
    except Exception as e:
        logging.warning(f"Error aplicando metadatos: {e}")


def download_and_apply_cover(file_path, metadata):
    try:
        artist = metadata.get('artist', '')
        album = metadata.get('album', '')

        if not artist or not album:
            return

        cover_bytes = None

        # Fuente 1: MusicBrainz + CoverArtArchive
        try:
            search = musicbrainzngs.search_releases(
                query=f'artist:"{artist}" release:"{album}"',
                limit=1
            )

            if search.get('release-list'):
                release_id = search['release-list'][0]['id']
                cover_url = f"https://coverartarchive.org/release/{release_id}/front"
                response = requests.get(cover_url, timeout=10)
                if response.status_code == 200:
                    cover_bytes = response.content
        except Exception:
            pass

        # Fuente 2: Deezer (fallback sin autenticacion)
        if cover_bytes is None:
            try:
                query = f'artist:"{artist}" album:"{album}"'
                response = requests.get(
                    'https://api.deezer.com/search/album',
                    params={'q': query},
                    timeout=10
                )
                if response.status_code == 200:
                    payload = response.json()
                    albums = payload.get('data') or []
                    if albums:
                        image_url = albums[0].get('cover_xl') or albums[0].get('cover_big') or albums[0].get('cover_medium')
                        if image_url:
                            img_response = requests.get(image_url, timeout=10)
                            if img_response.status_code == 200:
                                cover_bytes = img_response.content
            except Exception:
                pass

        if cover_bytes and not has_embedded_cover(file_path):
            embed_cover(file_path, cover_bytes, mime='image/jpeg')

    except Exception:
        pass


def has_embedded_cover(file_path):
    try:
        suffix = Path(file_path).suffix.lower()
        if suffix == '.mp3':
            try:
                tags = ID3(file_path)
            except ID3NoHeaderError:
                return False
            return bool(tags.getall('APIC'))
        if suffix in ('.m4a', '.mp4'):
            audio = MP4(file_path)
            return bool(audio.tags and audio.tags.get('covr'))
        return False
    except Exception:
        return False


def embed_cover(file_path, cover_bytes, mime='image/jpeg'):
    suffix = Path(file_path).suffix.lower()
    if suffix == '.mp3':
        try:
            tags = ID3(file_path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall('APIC')
        tags.add(APIC(
            encoding=3,
            mime=mime,
            type=3,
            desc='Cover',
            data=cover_bytes
        ))
        tags.save(file_path, v2_version=4)
        return

    if suffix in ('.m4a', '.mp4'):
        audio = MP4(file_path)
        img_fmt = MP4Cover.FORMAT_JPEG if mime == 'image/jpeg' else MP4Cover.FORMAT_PNG
        audio['covr'] = [MP4Cover(cover_bytes, imageformat=img_fmt)]
        audio.save()


@app.route('/api/status/<int:queue_id>')
def get_status(queue_id):
    if queue_id in DOWNLOAD_QUEUE:
        return jsonify(DOWNLOAD_QUEUE[queue_id])
    return jsonify({'error': 'No encontrado'}), 404


@app.route('/api/queue')
def get_queue():
    items = sorted(
        DOWNLOAD_QUEUE.values(),
        key=lambda x: x.get('queue_id', 0),
        reverse=True
    )
    return jsonify(items)


@app.route('/api/queue/<int:queue_id>/control', methods=['POST'])
def control_queue(queue_id):
    queue = DOWNLOAD_QUEUE.get(queue_id)
    if not queue:
        return jsonify({'error': 'No encontrado'}), 404

    action = (request.json or {}).get('action', '').strip().lower()
    if action == 'pause':
        queue['pause_requested'] = True
        queue['status'] = 'pausado'
        queue['message'] = 'Descarga en pausa'
    elif action == 'resume':
        queue['pause_requested'] = False
        if queue.get('status') == 'pausado':
            queue['status'] = 'descargando'
            queue['message'] = 'Reanudando descarga...'
    elif action == 'cancel':
        queue['cancel_requested'] = True
        queue['pause_requested'] = False
        queue['message'] = 'Cancelando descarga...'
    else:
        return jsonify({'error': 'Accion no valida'}), 400

    update_history_entry(queue.get('history_id'), {
        'status': queue.get('status'),
        'progress': queue.get('progress', 0),
        'destination': queue.get('destination'),
    })
    return jsonify({'status': 'ok', 'queue_id': queue_id, 'action': action})


@app.route('/api/history')
def get_history():
    items = sorted(
        load_history(),
        key=lambda x: (x.get('updated_at') or x.get('created_at') or ''),
        reverse=True
    )
    return jsonify(items[:100])


def count_media_files(path_obj):
    if not path_obj.exists():
        return 0
    media_exts = {'.mp3', '.m4a', '.wav', '.flac', '.ogg', '.opus', '.mp4', '.mkv', '.webm'}
    count = 0
    try:
        for file_path in path_obj.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in media_exts:
                count += 1
    except Exception:
        return 0
    return count


@app.route('/api/history/<history_id>/validate', methods=['POST'])
def validate_history_item(history_id):
    item = get_history_entry(history_id)
    if not item:
        return jsonify({'error': 'Historial no encontrado'}), 404

    destination = Path((item.get('destination') or '')).expanduser()
    payload = item.get('request_payload') or {}
    expected = 1
    if item.get('kind') == 'playlist':
        expected = len(payload.get('selected_items') or payload.get('videos') or []) or int(item.get('downloaded') or 0) or 1

    media_count = count_media_files(destination) if destination.exists() else 0
    missing = max(0, expected - media_count)
    looks_ok = destination.exists() and media_count >= max(1, min(expected, 1 if item.get('kind') == 'single' else expected))

    return jsonify({
        'history_id': history_id,
        'destination': str(destination),
        'exists': destination.exists(),
        'kind': item.get('kind') or 'single',
        'expected_items': expected,
        'media_files_found': media_count,
        'missing_items': missing,
        'looks_complete': bool(looks_ok),
        'suggestion': ('Reintentar con "Forzar redescarga" para recuperar faltantes.' if (not looks_ok or missing > 0) else 'Sin faltantes evidentes en la carpeta destino.')
    })


def has_active_downloads():
    active_states = {'iniciando', 'analizando', 'descargando', 'pausado'}
    for queue in DOWNLOAD_QUEUE.values():
        if queue.get('status') in active_states:
            return True
    return False


@app.route('/api/history/clear', methods=['POST'])
def clear_history():
    if has_active_downloads():
        return jsonify({'error': 'Hay descargas activas. Pausa o cancela antes de limpiar historial.'}), 409
    save_history([])
    return jsonify({'status': 'ok', 'cleared': 'history'})


@app.route('/api/archive/clear', methods=['POST'])
def clear_archive():
    if has_active_downloads():
        return jsonify({'error': 'Hay descargas activas. Pausa o cancela antes de limpiar archivo de descargas.'}), 409
    config = load_config()
    archive_file = Path(config.get('archive_file') or DEFAULT_CONFIG['archive_file']).expanduser()
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    archive_file.write_text('', encoding='utf-8')
    return jsonify({'status': 'ok', 'cleared': 'archive', 'archive_file': str(archive_file)})


@app.route('/api/maintenance/clear-all', methods=['POST'])
def clear_all_maintenance():
    if has_active_downloads():
        return jsonify({'error': 'Hay descargas activas. Pausa o cancela antes de limpiar.'}), 409
    config = load_config()
    archive_file = Path(config.get('archive_file') or DEFAULT_CONFIG['archive_file']).expanduser()
    archive_file.parent.mkdir(parents=True, exist_ok=True)
    archive_file.write_text('', encoding='utf-8')
    save_history([])
    return jsonify({'status': 'ok', 'cleared': 'all', 'archive_file': str(archive_file)})


@app.route('/api/maintenance/remove-metadata-json', methods=['POST'])
def remove_metadata_json():
    if has_active_downloads():
        return jsonify({'error': 'Hay descargas activas. Espera a que terminen antes de limpiar.'}), 409
    payload = request.get_json(silent=True) or {}
    if payload.get('confirm') is not True:
        return jsonify({'error': 'Confirmacion requerida.'}), 400
    library_root = Path(load_config().get('download_path') or DEFAULT_CONFIG['download_path'])
    removed = remove_generated_sidecars(library_root)
    LOGGER.info("Eliminados %s sidecars antiguos de metadatos bajo %s", len(removed), library_root)
    return jsonify({
        'status': 'ok',
        'removed': len(removed),
        'root': str(library_root),
    })


@app.route('/api/open-folder', methods=['POST'])
def open_folder():
    target = (request.json or {}).get('path') or ''
    if not target:
        return jsonify({'error': 'Ruta requerida'}), 400

    path = Path(target).expanduser().resolve()
    if not path.exists():
        return jsonify({'error': 'La ruta no existe'}), 404
    library_root = Path(load_config().get('download_path') or DEFAULT_CONFIG['download_path']).expanduser().resolve()
    try:
        path.relative_to(library_root)
    except ValueError:
        if path != library_root:
            return jsonify({'error': 'La ruta esta fuera de la biblioteca configurada'}), 403

    try:
        os.startfile(str(path))
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/history/<history_id>/retry', methods=['POST'])
def retry_history_item(history_id):
    item = get_history_entry(history_id)
    if not item:
        return jsonify({'error': 'Historial no encontrado'}), 404

    payload = dict(item.get('request_payload') or {})
    if not isinstance(payload, dict) or not payload.get('url'):
        return jsonify({'error': 'No hay payload guardado para reintentar'}), 400
    payload['reuse_history_id'] = history_id
    retry_options = request.json or {}
    if bool(retry_options.get('force_redownload')):
        payload['force_redownload'] = True

    kind = item.get('kind') or 'single'
    try:
        existing_queue_id = None
        if payload.get('url'):
            existing_queue_id = find_active_duplicate_queue('playlist' if kind == 'playlist' else 'single', payload.get('url'))
        if kind == 'playlist':
            queue_id = start_playlist_download(payload)
        else:
            queue_id = start_single_download(payload)
        duplicated = bool(existing_queue_id and existing_queue_id == queue_id)
        return jsonify({
            'queue_id': queue_id,
            'duplicate': duplicated,
            'message': ('Ya existe una descarga activa para esa URL; se reutilizo la cola existente.' if duplicated else '')
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='YT-Descargar')
    parser.add_argument('--port', type=int, default=5000, help='Puerto HTTP local (default: 5000)')
    parser.add_argument('--host', default='127.0.0.1', help='Host local (default: 127.0.0.1)')
    parser.add_argument('--debug', action='store_true', help='Activa modo debug de Flask')
    args = parser.parse_args()

    app.run(debug=args.debug, port=args.port, host=args.host)
