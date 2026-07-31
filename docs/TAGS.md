# Etiquetas, procedencia y compatibilidad

## Campos principales

| Grupo | Ejemplos | MP3 | M4A/MP4 | FLAC/OGG/OPUS | WAV |
|---|---|---:|---:|---:|---:|
| Biblioteca | título, artista, álbum, album artist | Sí | Sí | Sí | Sí |
| Orden | año/fecha, pista/total, disco/total | Sí | Sí | Sí | Sí |
| Créditos | compositor, sello, copyright | Sí | Sí/custom | Sí | Sí |
| Clasificación | género, idioma, BPM, agrupación, mood | Sí | Sí/custom | Sí | Sí |
| Identidad | ISRC, MusicBrainz IDs, catálogo, barcode | Sí/custom | Libre iTunes | Vorbis | ID3 |
| Lanzamiento | tipo, país, estado | TXXX | Libre iTunes | Vorbis | TXXX |
| Procedencia | YouTube ID, canal, uploader, URL, licencia | TXXX | Libre iTunes | Vorbis | TXXX |
| Técnica | codecs, formato, resolución, bitrate fuente | TXXX | Libre iTunes | Vorbis | TXXX |
| Contenido | descripción, categorías, keywords, capítulos | TXXX/COMM | Libre iTunes | Vorbis | ID3 |
| Letras | USLT | `©lyr` | `LYRICS` | USLT |
| Portada | APIC | `covr` | Pendiente | Limitado |

YT-Descargar no crea sidecars `.info.json`: toda la información compatible se
incrusta en el propio archivo. MKV, WebM y AAC todavía no reciben tags internos
del módulo actual.

Las letras se obtienen primero de subtítulos o captions disponibles en YouTube.
Si no existen, se solicita una coincidencia exacta a
[LRCLIB](https://lrclib.net/docs) usando artista, título, álbum y duración. Se
guardan como letra no sincronizada junto con la fuente y su ID. Si ninguna
fuente encuentra texto, la descarga continúa sin inventarlo.

## Precedencia

1. Valor manual.
2. Valor detectado por yt-dlp.
3. Coincidencia MusicBrainz de alta confianza para campos vacíos.
4. Valor predeterminado de Configuración.
5. Vacío.

Los IDs de procedencia se pueden agregar sin reemplazar títulos/créditos
manuales. MusicBrainz requiere título y artista válidos, puntuación ≥ 90 y
coincidencia normalizada.

## Calidad

El bitrate de salida no implica que la fuente tenga esa calidad. Convertir
Opus/AAC a MP3 320 kbps mejora compatibilidad, no recupera detalle perdido. Para
reducir transcodificación usa M4A u OPUS; para compatibilidad amplia usa MP3.
