# Dependencias, APIs y privacidad

Este documento enumera lo que usa YT-Descargar, para qué se usa y qué información
sale del equipo. La aplicación funciona en `127.0.0.1` y no requiere una cuenta propia.

## Dependencias de ejecución

| Componente | Versión declarada | Uso | Dirección oficial |
|---|---|---|---|
| Python | 3.10 o posterior | Backend y tareas | https://www.python.org/ |
| Flask | `>=3.1,<4` | Servidor web local | https://flask.palletsprojects.com/ |
| Flask-Cors | `>=5,<7` | CORS limitado a loopback | https://flask-cors.readthedocs.io/ |
| yt-dlp | `>=2026.6.9` | Detección y descarga autorizada | https://github.com/yt-dlp/yt-dlp |
| FFmpeg/ffprobe | disponible en `PATH` o `ffmpeg_portable/` | Conversión y análisis multimedia | https://ffmpeg.org/ |
| Mutagen | `>=1.47,<2` | Lectura y escritura de tags | https://mutagen.readthedocs.io/ |
| musicbrainzngs | `>=0.7.1,<1` | Cliente MusicBrainz | https://python-musicbrainzngs.readthedocs.io/ |
| ytmusicapi | `>=1.12.1,<2` | Consulta opcional de álbumes y créditos públicos de YouTube Music | https://ytmusicapi.readthedocs.io/ |
| Pillow | `>=11,<13` | Validación y recorte cuadrado de covers | https://pillow.readthedocs.io/ |
| Requests | `>=2.32,<3` | HTTP con timeouts y límites | https://requests.readthedocs.io/ |

Instalación:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app_playlist.py
```

`ytmusicapi` es un paquete Python puro (`py3-none-any`). AcoustID se integra
directamente con `requests` y el ejecutable oficial `fpcalc`, sin instalar otro
cliente Python. La presencia de estas dependencias no activa consultas ni
autenticación automáticamente. `fpcalc` no se incluye en `ffmpeg_portable/`.

## Servicios externos

| Servicio | Endpoint utilizado | Datos enviados | Autenticación y comportamiento |
|---|---|---|---|
| YouTube / YouTube Music | URL introducida por el usuario, procesada por yt-dlp | URL, cookies sólo si el usuario las configura | Sin clave de API; sujeto a disponibilidad del sitio y derechos del contenido |
| ytmusicapi | Endpoints internos usados por el cliente web de YouTube Music | IDs de canción/álbum y consultas textuales; cookies únicamente si el usuario las autoriza | API no oficial; las lecturas públicas no requieren cuenta y las operaciones de cuenta permanecen desactivadas |
| MusicBrainz | `https://musicbrainz.org/ws/2/` | título, artista y, si existe, álbum | Sin clave; User-Agent identificable, caché y límite de solicitudes |
| AcoustID | `https://api.acoustid.org/v2/lookup` | fingerprint Chromaprint, duración y clave de aplicación; nunca el audio ni su ruta local | Requiere `ACOUSTID_API_KEY`; sólo búsqueda, máximo 3 solicitudes/segundo y sin envío de fingerprints |
| Cover Art Archive | `https://coverartarchive.org/release/{mbid}/front-1200` | MusicBrainz release ID | Sin clave; sólo se usa para una coincidencia de lanzamiento confiable |
| Deezer | `https://api.deezer.com/search/album` | artista y álbum | Sin clave en esta consulta pública; respaldo conservador y sujeto a cambios del servicio |
| LRCLIB | `https://lrclib.net/api/get` | artista, título, álbum y duración | Sin clave; respaldo de letras con identificación y rate limit |
| GitHub Releases | `https://api.github.com/repos/rafaeln0h/YT-Descargar/releases/latest` | versión local indirectamente; ETag en revisiones posteriores | Sin token para repositorio público; caché, ETag y comprobación manual/limitada |

Las descargas no fallan sólo porque MusicBrainz, covers, letras o actualizaciones no
respondan. Los clientes externos nunca reciben rutas arbitrarias de la computadora.
Los covers se aceptan únicamente desde hosts permitidos, con HTTPS, tipo de contenido
de imagen y límite de tamaño; después se normalizan como JPEG cuadrado.

## Configuración del enriquecimiento musical

### ytmusicapi

La integración se limita a consultas públicas de canción, álbum y artista. No descarga
audio y no debe crear, editar o borrar playlists ni historial. De forma predeterminada
se instancia sin credenciales. Si una función futura requiere cuenta, debe pedir
consentimiento separado, guardar OAuth/cookies fuera del repositorio y mostrar qué
datos se enviarán. Una respuesta incompleta o un cambio de la API no oficial activa el
fallback a yt-dlp y MusicBrainz.

### MusicBrainz

No necesita API key. Toda solicitud usa un User-Agent con nombre, versión y URL del
proyecto, caché local y como máximo una solicitud por segundo. Se consulta sólo con
artista y título válidos; el álbum se utiliza para escoger lanzamiento. Los resultados
con score menor a 90 o identidad textual incompatible se descartan. Un error `503`,
timeout o modo sin conexión deja los campos vacíos y no detiene la descarga.

### AcoustID y Chromaprint

El fingerprint se calcula localmente. Al servicio sólo se envían fingerprint, duración
y clave de aplicación; no se sube el archivo. La aplicación debe realizar únicamente
`lookup`, nunca `submit`. Para habilitarlo en Windows:

1. Instala `fpcalc` desde [Chromaprint](https://acoustid.org/chromaprint) y conserva
   la ruta exacta al ejecutable.
2. Registra una clave de aplicación en [AcoustID](https://acoustid.org/api-key).
3. Define las variables sólo para la sesión o mediante la configuración segura del
   sistema, nunca dentro del código:

```powershell
$env:FPCALC = 'C:\Herramientas\Chromaprint\fpcalc.exe'
$env:ACOUSTID_API_KEY = 'tu-clave-de-aplicacion'
```

Si falta cualquiera de estos requisitos, el enriquecimiento acústico queda en estado
`disabled` y continúa la jerarquía normal. Un score acústico sólo confirma la identidad
del recording; título, álbum, créditos y género siguen sujetos a sus propias fuentes y
umbrales. El servicio gratuito de AcoustID está limitado a uso no comercial y un máximo
de tres solicitudes por segundo.

### Fallbacks y privacidad

La secuencia es: valores manuales → identidad acústica corroborada → álbum oficial de
YouTube Music → MusicBrainz verificado → yt-dlp → predeterminados → vacío reportado.
Ningún servicio puede reemplazar datos manuales. El género nunca se inventa; si no hay
una fuente explícita queda vacío y se registra en `METADATA_MISSING`. La procedencia,
confianza y campos ausentes se incrustan para que cada decisión sea auditable.

## APIs del navegador

- Notifications API: sólo después de consentimiento; avisa al terminar una lista o
  ante un error relevante y evita repetir avisos.
- Service Worker: mantiene notificaciones de la PWA y abre `/#activity`.
- Media Session API: publica título, artista, álbum y controles durante la reproducción.
- View Transitions API: mejora cambios de pestaña si el navegador la soporta; existe
  una animación CSS de respaldo y se respeta `prefers-reduced-motion`.
- Clipboard API: se usa únicamente al pulsar **Pegar enlace**.
- `localStorage`: conserva preferencias de interfaz y deduplicación de avisos; las
  descargas activas viven en la cola persistente del backend.

## Herramientas opcionales de desarrollo

El proyecto no depende de herramientas privadas ni de rutas de una computadora
concreta. Para contribuir se recomiendan [Git](https://git-scm.com/),
[GitHub CLI](https://cli.github.com/) y
[Playwright](https://playwright.dev/) para la validación visual. No forman parte de
las dependencias de ejecución ni se instalan en los equipos de usuarios finales.

## Verificación para desarrolladores

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m compileall app_playlist.py ymd
ruff check app_playlist.py ymd tests
node --check static/js/app-shell.js
```

Las fuentes de investigación y proyectos de referencia están listadas en
[SOURCES.md](SOURCES.md) y [RESEARCH.md](RESEARCH.md). La política de contenido está
en [LEGAL.md](LEGAL.md).
