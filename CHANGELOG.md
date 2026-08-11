# Changelog

Este proyecto sigue un esquema incremental propio (`0.012`, `0.013`, …).

## [0.013] - 2026-08-10

- Actualización reproducible a `yt-dlp 2026.07.04` con sus extras oficiales de
  EJS, Deno y `curl-cffi`; Node.js queda disponible como respaldo automático.
- Selección automática del cliente de YouTube en lugar de forzar `web_music`,
  evitando avisos masivos de GVS PO Token y formatos propensos a HTTP 403.
- Diagnóstico visible de Python, yt-dlp, EJS, runtime JavaScript, FFmpeg y
  proveedores opcionales de PO Token.
- Python mínimo actualizado a 3.11 y CI validada en Python 3.11 y 3.13.
- GitHub Actions actualizadas a `actions/checkout@v7` y
  `actions/setup-python@v7`; las releases adjuntan ZIP y checksum SHA-256.
- Detección ordenada de discografías: los enlaces de artista combinan álbumes,
  singles, EPs y playlists; las secciones `/browse/MPAD...` muestran únicamente
  lanzamientos oficiales con artista, tipo y año correctos.
- Filtros independientes para álbumes, singles, EPs, playlists y videos, con una
  selección de discografía segura que evita videos del canal por defecto.
- Recordatorio interno después de detectar, contador en la pestaña Descargas y
  aviso flotante de progreso que permanece al navegar por la aplicación.
- Organización específica de sencillos: una sola carpeta `Singles` por artista,
  separación opcional por año, carpeta por lanzamiento o plantilla personalizada,
  disponible tanto en Configuración como en el menú de descarga.
- Reconciliación automática de la cola local del navegador con el historial y la
  cola persistente para retirar pendientes que el backend ya recibió o completó.

## [0.012] - 2026-07-31

- Interfaz completa inspirada en YouTube Music en las páginas principales, con
  pestañas, animaciones accesibles, biblioteca lateral y reproducción integrada.
- Se elimina la ruta experimental `/suite`; sus funciones permanecen conectadas
  desde el descargador y Configuración.
- Covers cuadrados de alta calidad con prioridad para el arte del álbum, procedencia
  incrustada y reparación opcional de bibliotecas existentes.
- Biblioteca moderna navegable por artistas, álbumes, playlists, canciones y videos,
  con covers reales, distintivo y panel de letras.
- Reproductor con cola contextual, anterior/siguiente, shuffle, repetición, volumen,
  Media Session y recuperación automática si un archivo desaparece.
- Escaneo incremental en memoria por tamaño y fecha de modificación, tolerante a
  archivos borrados, corruptos, inaccesibles o movidos durante la exploración.
- Cola por lotes persistente en el backend y respaldo local de tareas aún no
  enviadas.
- Enriquecimiento de álbumes oficiales de YouTube Music mediante una sola pista
  completa para conservar artista del álbum, año, álbum y numeración.
- PWA, service worker, notificaciones con consentimiento y Media Session.
- Reparación inteligente de la biblioteca existente, overrides manuales,
  fingerprint acústico opcional, Discogs y análisis ReplayGain.
- Limpieza de cachés y entorno roto, retirada de la dependencia redundante
  `pyacoustid` y consolidación del workflow de publicación.

### Añadido

- Fuente única de versión y endpoint de capacidades.
- Metadatos de procedencia y técnicos obtenidos de la respuesta pública de
  yt-dlp: IDs, canal, fechas, duración, descripción, licencia, categorías,
  keywords, capítulos, codecs, formato, resolución y bitrate.
- Enriquecimiento opcional de alta confianza con MusicBrainz: IDs estables,
  ISRC, sello, catálogo, código de barras, país/estado/tipo de lanzamiento y
  género.
- Metadatos incrustados directamente sin crear sidecars `.info.json`.
- Letras incrustadas en MP3, M4A/MP4, FLAC, OGG/OPUS y WAV cuando existen.
- Respaldo de letras mediante LRCLIB con coincidencia conservadora por artista,
  título y duración, rate limit e identificación del cliente.
- Nuevos campos manuales y predeterminados en la interfaz.
- Biblioteca local segura, búsqueda, minirreproductor y streaming HTTP Range.
- Logs rotativos, salud, documentación técnica y archivos comunitarios.

### Seguridad y privacidad

- No se guardan URLs firmadas de streams en los tags.
- Los IDs de biblioteca se validan contra la raíz configurada.
- CORS se limita a orígenes loopback.

### Cambiado

- La identidad del proyecto pasa a `YT-Descargar`.
- La versión anterior de desarrollo `2.0.0` se normaliza como primera entrega
  pública `0.012`.

[0.012]: https://github.com/rafaeln0h/YT-Descargar/releases/tag/v0.012
[0.013]: https://github.com/rafaeln0h/YT-Descargar/releases/tag/v0.013
