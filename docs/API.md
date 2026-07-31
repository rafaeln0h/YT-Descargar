# API local

Base predeterminada: `http://127.0.0.1:5000`.

La API de v0.012 no implementa autenticación y sólo debe exponerse en loopback.
No publiques el puerto en Internet.

## Cola persistente

### `GET /api/batch-queue`

Lista hasta 100 tareas persistentes sin devolver sus payloads completos. Los
estados son `pending`, `starting`, `running`, `completed`, `error` y
`cancelled`.

### `POST /api/batch-queue`

Recibe `{"jobs": [{"kind": "single|playlist", "label": "...", "payload": {...}}]}`.
Acepta hasta 50 tareas, evita URLs activas duplicadas y las ejecuta en secuencia
desde el backend.

### `POST /api/batch-queue/<job_id>/control`

Acciones: `cancel`, `retry` y `remove`. Una tarea que estaba ejecutándose cuando
se cerró el proceso vuelve a `pending` al recuperarse; el archivo de descargas
de yt-dlp evita repetir elementos ya terminados.

## Diagnóstico

### `GET /api/system/health`

Devuelve salud, versión, canal, etiqueta de release, raíz de descargas, estado
del archivo anti-duplicados y ruta de logs.

### `GET /api/system/capabilities`

Contrato de descubrimiento para futuros clientes. Devuelve funciones, formatos,
contenedores etiquetables, fuentes de metadata y plataformas actuales/planeadas.
Los clientes deben probar capacidades; no inferirlas sólo por versión.

### `GET /api/system/update`

Consulta de forma limitada la última GitHub Release estable. Usa caché local y ETag; una
caída de GitHub nunca bloquea las descargas. `?force=1` fuerza una comprobación para
diagnóstico. Devuelve `update_available`, `current_version` y `latest_release`.

### `GET /api/system/logs?limit=200`

Devuelve entre 1 y 1000 líneas recientes. Los logs no deben contener secretos.

## Mantenimiento de covers

### `GET /api/maintenance/repair-covers`

Devuelve el estado de la reparación en segundo plano: `running`, álbumes y archivos
procesados, fallos y último mensaje. No modifica archivos por sí solo.

### `POST /api/maintenance/repair-covers`

Inicia una revisión agrupada por artista del álbum y álbum. Sólo reemplaza la imagen
cuando encuentra una fuente admitida y puede normalizarla como JPEG cuadrado. Rechaza
el inicio si hay descargas activas o si ya existe otra reparación en ejecución.

La operación se inicia explícitamente desde **Configuración > Sistema**; no se ejecuta
automáticamente al abrir la aplicación.

## Biblioteca

### `GET /api/library?limit=300&q=texto`

Escanea la raíz configurada y devuelve medios y un catálogo agregado en `summary`,
`artists`, `albums` y `playlists`. Cada agrupación incluye IDs de pistas y un cover
representativo. `q` busca en título, artista, álbum, playlist, nombre y ruta relativa.
El máximo actual es 2000 elementos por respuesta.

### `GET /api/library/media/<media_id>`

Transmite un archivo con `Range`, ETag y validación de ruta. `media_id` es un
identificador opaco generado por la biblioteca; no es una ruta de filesystem.

### `GET /api/library/artwork/<media_id>`

Extrae el cover incrustado sin revelar la ruta del archivo. Soporta APIC de MP3/WAV,
`covr` de M4A/MP4 y pictures de FLAC/Ogg/Opus. Si un video no contiene cover,
FFmpeg genera un poster bajo demanda sin crear un sidecar. Responde con ETag y caché
de un día.

### `GET /api/library/lyrics/<media_id>`

Devuelve `{"media_id": "...", "lyrics": "..."}` sólo si el contenedor tiene letras
incrustadas. La letra no se incluye en el catálogo para evitar respuestas pesadas.

### `POST /api/library/rescan`

Vacía la caché derivada de tags, vuelve a explorar la carpeta y devuelve el catálogo
actualizado. Los archivos eliminados dejan de aparecer; un archivo que desaparece,
está corrupto o pierde permisos durante el escaneo se omite sin detener los demás.

## Evolución

Antes de acceso remoto o móvil se requiere:

- prefijo versionado (`/api/v1`);
- autenticación y revocación;
- CORS explícito;
- límites por tamaño/tasa;
- IDs persistentes de jobs;
- OpenAPI y pruebas de contrato.
