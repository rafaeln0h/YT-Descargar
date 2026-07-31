# YT-Descargar

[![Versión](https://img.shields.io/badge/versión-0.012-6c5ce7)](CHANGELOG.md)
[![Pruebas](https://github.com/rafaeln0h/YT-Descargar/actions/workflows/tests.yml/badge.svg)](https://github.com/rafaeln0h/YT-Descargar/actions/workflows/tests.yml)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-2d3436)](LICENSE)

Aplicación local, gratuita y de código abierto para detectar, descargar,
etiquetar, organizar y reproducir contenido autorizado de YouTube y YouTube
Music mediante `yt-dlp` y FFmpeg.

> Descarga únicamente contenido propio, de dominio público, con licencia
> compatible o para el que tengas permiso expreso. Lee [Uso legal](docs/LEGAL.md).

![Pantalla principal de YT-Descargar](docs/assets/screenshots/inicio-v0.012.png)

![Etiquetas avanzadas de v0.012](docs/assets/screenshots/metadatos-v0.012.png)

## Funciones de v0.012

- Videos, canciones, playlists, álbumes y canales.
- Audio MP3, M4A, FLAC, OGG/OPUS y WAV; video MP4 y MKV.
- Cola, reintentos, pausa/cancelación, archivo anti-duplicados e historial.
- Tags musicales, técnicos y de procedencia en formatos compatibles.
- Enriquecimiento opcional de alta confianza con MusicBrainz.
- Metadatos incrustados directamente; no crea archivos `.info.json`.
- Portada y letras desde captions/LRCLIB, plantillas de carpetas y nombres.
- Biblioteca local, búsqueda y minirreproductor con HTTP Range.
- Logs rotativos y endpoints de salud/capacidades.

## Inicio rápido en Windows

1. Instala [Python 3.10 o posterior](https://www.python.org/downloads/windows/).
2. Ejecuta `start.bat`.
3. Abre `http://127.0.0.1:5000` si el navegador no se abre solo.
4. Pega una URL, pulsa **Detectar**, revisa formato y tags, y descarga.
5. Abre **Biblioteca** para reproducir los archivos locales.

Instalación manual:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app_playlist.py
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app_playlist.py
```

FFmpeg debe estar en `PATH` o en `ffmpeg_portable/`. Consulta
[Solución de problemas](docs/TROUBLESHOOTING.md).

## Estructura

```text
app_playlist.py          Orquestación y compatibilidad Flask
ymd/
  enrichment.py          Enriquecimiento MusicBrainz con caché y rate limit
  library.py             Biblioteca segura y resolución de medios
  logging_config.py      Logs estructurados y rotativos
  metadata.py            Modelo, tags y letras multiformato
  routes.py              API de biblioteca y diagnóstico
  version.py             Fuente única de versión
static/                  Estilos y minirreproductor
templates/               Interfaz Flask
tests/                   Pruebas unitarias
docs/                    Diseño, fuentes, roadmap y operación
```

## API local

| Endpoint | Uso |
|---|---|
| `GET /api/library?limit=300&q=texto` | Lista medios bajo la raíz configurada |
| `GET /api/library/media/<id>` | Reproduce con soporte HTTP Range |
| `GET /api/system/health` | Salud, versión y rutas activas |
| `GET /api/system/capabilities` | Capacidades para clientes futuros |
| `GET /api/system/logs?limit=200` | Últimas líneas del log |

Los identificadores de medios no aceptan rutas libres: se resuelven dentro de
la biblioteca configurada. La aplicación escucha en localhost por defecto.

## Desarrollo

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m compileall app_playlist.py ymd
ruff check app_playlist.py ymd tests
```

Antes de proponer cambios, lee [CONTRIBUTING.md](CONTRIBUTING.md),
[GOVERNANCE.md](GOVERNANCE.md) y [SECURITY.md](SECURITY.md). Toda integración
requiere revisión y aprobación del mantenedor `@rafaeln0h`.

## Documentación

- [Notas de v0.012](docs/releases/v0.012.md)
- [Arquitectura](docs/ARCHITECTURE.md)
- [Tags y letras](docs/TAGS.md)
- [API local](docs/API.md)
- [Comparativa comercial](docs/COMMERCIAL_COMPARISON.md)
- [Fuentes y atribuciones](docs/SOURCES.md)
- [Roadmap v0.013–v0.016](docs/ROADMAP.md)
- [Plan móvil y multiplataforma](docs/MOBILE_AND_CROSS_PLATFORM.md)
- [Proceso de publicación](docs/RELEASE_PROCESS.md)
