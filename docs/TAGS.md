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
| Portada | APIC | `covr` | `METADATA_BLOCK_PICTURE` | APIC/ID3 |

YT-Descargar no crea sidecars `.info.json`: toda la información compatible se
incrusta en el propio archivo. MKV, WebM y AAC todavía no reciben tags internos
del módulo actual.

Las letras se obtienen primero de subtítulos o captions disponibles en YouTube.
Si no existen, se solicita una coincidencia exacta a
[LRCLIB](https://lrclib.net/docs) usando artista, título, álbum y duración. Se
guardan como letra no sincronizada junto con la fuente y su ID. Si ninguna
fuente encuentra texto, la descarga continúa sin inventarlo.

## Covers

La portada se resuelve por álbum, no por el fotograma o thumbnail de cada video. El
orden es: imagen cuadrada del álbum oficial de YouTube Music, Cover Art Archive,
coincidencia exacta de Deezer, imagen de playlist y, sólo como último recurso,
thumbnail del video. Todas las imágenes se validan, se convierten a RGB y se recortan
al centro en formato cuadrado antes de incrustarse. Los tags también registran fuente,
URL y dimensiones del cover para poder auditar el resultado.

## Jerarquía de fuentes

La procedencia se decide por campo. Una fuente de mayor prioridad nunca autoriza a
sobrescribir un valor manual y una coincidencia de identidad no convierte en fiables
todos los campos de esa respuesta.

1. **Valor manual confirmado por el usuario**: prioridad máxima y confianza `1.00`.
2. **Identidad acústica AcoustID + MusicBrainz**: sirve para confirmar el recording
   cuando el fingerprint, la duración y la identidad textual coinciden. No sustituye
   por sí sola el álbum elegido por el usuario.
3. **Álbum oficial de YouTube Music**: `ytmusicapi` o los campos musicales de yt-dlp
   aportan título, artista, album artist, álbum, fecha, posición y totales.
4. **MusicBrainz**: sólo rellena campos vacíos con puntuación ≥ 90, título normalizado
   exacto y artista compatible. Si se indicó álbum, se prefiere ese lanzamiento.
5. **yt-dlp**: conserva identidad de YouTube, URL, canal y datos técnicos; sus campos
   musicales se usan cuando no hay una fuente musical más específica.
6. **Valores predeterminados**: únicamente rellenan campos configurados y vacíos.
7. **Vacío y reportado**: es preferible a inventar un dato.

Los identificadores y la procedencia se agregan de forma acumulativa sin reemplazar
títulos ni créditos manuales. Una consulta fallida nunca debe impedir que el archivo
termine de descargarse y etiquetarse con los datos disponibles.

## Confianza y auditoría

Cada archivo puede conservar estos campos de auditoría:

| Campo | Contenido |
|---|---|
| `METADATA_SOURCES_USED` | Fuentes realmente utilizadas, separadas por `; ` |
| `METADATA_CONFIDENCE` | Confianza global entre `0.00` y `1.00`; no es un porcentaje inventado |
| `METADATA_MISSING` | Campos valiosos que siguen vacíos |
| `ENRICHMENT_STATUS` | `complete`, `partial`, `unmatched`, `offline` o `disabled` |
| `CREDITS_SOURCE` | Fuente concreta de compositor, letrista, productor o intérpretes |

Guía para decisiones automáticas:

- `0.90–1.00`: coincidencia verificada; puede completar campos vacíos.
- `0.80–0.89`: alta, pero requiere coincidencia de álbum para cambiar datos de álbum.
- `0.65–0.79`: apoyo informativo; no reemplaza identidad ni créditos.
- Menor a `0.65`: se conserva sólo para diagnóstico, no para escribir tags finales.

La confianza debe provenir de señales observables: puntuación del servicio,
coincidencia normalizada de artista/título/álbum, diferencia de duración e identidad
acústica. No debe generarse una cifra arbitraria cuando una fuente no publica score.

### Política de género

El género sólo se escribe si procede de un valor manual, un género explícito del
álbum o una etiqueta MusicBrainz con evidencia. No se deduce a partir del nombre del
canal, descripción, portada, letras, popularidad ni preferencias del usuario. Si no
hay evidencia, `GENRE` queda vacío y `genre` aparece en `METADATA_MISSING`.

## Compatibilidad MusicBrainz Picard

Los identificadores siguen los nombres que Picard reconoce en cada contenedor:

| Valor | ID3v2 | MP4/iTunes | Vorbis |
|---|---|---|---|
| Recording MBID | `UFID:http://musicbrainz.org` | `MusicBrainz Track Id` | `MUSICBRAINZ_TRACKID` |
| Release MBID | `MusicBrainz Album Id` | `MusicBrainz Album Id` | `MUSICBRAINZ_ALBUMID` |
| Release group MBID | `MusicBrainz Release Group Id` | mismo nombre | `MUSICBRAINZ_RELEASEGROUPID` |
| Artist MBID | `MusicBrainz Artist Id` | mismo nombre | `MUSICBRAINZ_ARTISTID` |
| AcoustID | `Acoustid Id` | mismo nombre | `ACOUSTID_ID` |
| Fingerprint | `Acoustid Fingerprint` | mismo nombre | `ACOUSTID_FINGERPRINT` |

Para fechas, `TDRC`/`DATE` conserva la fecha completa del lanzamiento seleccionado y
`TDOR`/`ORIGINALDATE` conserva la primera fecha de publicación. Una ausencia de disco
no debe producir `TPOS=0`; el frame se omite.

Créditos estándar: compositor (`TCOM`), letrista (`TEXT`), director (`TPE3`), remixer
(`TPE4`), productor e intérpretes en campos compatibles. El contenido explícito se
registra como advisory (`ITUNESADVISORY=1` en ID3 y `rtng=4` en MP4), sin inferirlo de
palabras del título.

## Calidad

El bitrate de salida no implica que la fuente tenga esa calidad. Convertir
Opus/AAC a MP3 320 kbps mejora compatibilidad, no recupera detalle perdido. Para
reducir transcodificación usa M4A u OPUS; para compatibilidad amplia usa MP3.
# Reparación de bibliotecas existentes

La reparación es reversible y siempre debe comenzar con una simulación:

```powershell
.\.venv\Scripts\python.exe scripts\repair_library.py "C:\Users\TU_USUARIO\Music\YouTube" --enrich
.\.venv\Scripts\python.exe scripts\repair_library.py "C:\Users\TU_USUARIO\Music\YouTube" --apply --enrich
```

Cada aplicación crea un journal y respaldos semánticos de tags, cover y letras
dentro de `.ymd-repair`. El journal se puede revertir con `--rollback`. Para
calcular loudness y tags ReplayGain sin modificar el audio, añade
`--analyze-audio`; esta operación decodifica cada pista y puede tardar.

La interfaz ofrece las mismas acciones en **Configuración > Sistema >
Mantenimiento**. `POST /api/maintenance/repair-metadata` acepta `apply`,
`enrich` y `analyze_audio`.

Cuando los catálogos no tengan un dato, el archivo conserva el campo vacío y
recibe `METADATA_MISSING`, `ENRICHMENT_STATUS`, `METADATA_SOURCES_USED` y el
resumen de proveedores consultados. Las correcciones verificadas por el usuario
se guardan con `POST /api/metadata/overrides` en
`%USERPROFILE%\.ymd_metadata_overrides.json`.
