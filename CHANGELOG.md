# Changelog

Este proyecto sigue un esquema incremental propio (`0.012`, `0.013`, …).

## [0.012] - 2026-07-31

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
