# Biblioteca y reproductor

La biblioteca usa los archivos locales como única fuente de verdad. No mueve, elimina
ni renombra música durante un escaneo. Los datos visuales se derivan de los tags y de
la estructura de carpetas generada por YT-Descargar.

## Vistas

- **Inicio**: resumen, reproducir todo, aleatorio, artistas, álbumes, playlists y
  archivos recientes.
- **Artistas**: cada artista abre sus álbumes y canciones. Se usa `album_artist` y,
  si falta, `artist`.
- **Álbumes**: agrupa por artista del álbum + título para no mezclar discos homónimos.
- **Playlists**: usa primero el tag `PLAYLIST_TITLE`; como respaldo reconoce la ruta
  `Playlists/Nombre/...`.
- **Canciones y Videos**: listas independientes con búsqueda, formato, duración,
  cover y distintivos de letra/video.

El orden de un álbum es disco, pista y título. Una playlist prioriza
`PLAYLIST_POSITION`. Un artista ordena por fecha, álbum, disco y pista.

## Covers y letras

El catálogo sólo expone `has_cover`, `has_lyrics`, `artwork_url` y `lyrics_url`. Los
bytes se leen cuando el navegador necesita mostrarlos:

- MP3 y WAV: APIC / USLT.
- M4A y MP4: `covr` / `©lyr`.
- FLAC: picture blocks / `LYRICS`.
- Ogg y Opus: `metadata_block_picture` / `LYRICS`.

En videos sin imagen incrustada, FFmpeg extrae bajo demanda un poster JPEG del primer
segundo. Se conserva sólo en una caché limitada de memoria y no se crean archivos
adicionales junto al video.

Esto mantiene liviano `GET /api/library`. Los IDs son opacos y cada petición vuelve a
validar que el archivo permanezca dentro de la carpeta configurada.

## Controles del reproductor

- Reproducir o pausar.
- Canción anterior; si han pasado más de tres segundos, reinicia la actual.
- Canción siguiente.
- Aleatorio reversible, sin duplicar pistas.
- Repetición desactivada, de toda la cola o de una pista.
- Barra de progreso, volumen persistente y silencio.
- Panel de cola y panel de letras.
- Video en vista ampliada.
- Media Session del sistema con título, artista, álbum, cover, seek, anterior y
  siguiente.

Atajos cuando el foco no está en un campo:

| Tecla | Acción |
|---|---|
| Espacio | Reproducir/pausar |
| `N` / `P` | Siguiente/anterior |
| `M` | Silencio |
| Flechas izquierda/derecha | Retroceder/avanzar cinco segundos |
| Escape | Cerrar cola, letras o video |

## Escaneo y prevención de fallas

`GET /api/library` descubre archivos y conserva en memoria los tags usando como
fingerprint ruta, tamaño y `mtime_ns`. Si el archivo no cambió, no vuelve a analizar
Mutagen. **Reescanear carpeta** llama a `POST /api/library/rescan` y reconstruye la
caché derivada.

Durante el recorrido cada operación de archivo está aislada. Un borrado, cambio de
nombre, permiso insuficiente o tag corrupto no cancela el catálogo completo. Los
symlinks que resuelven fuera de la raíz se ignoran y el endpoint de streaming vuelve
a validar el destino.

Si un archivo desaparece mientras está en la cola, el reproductor:

1. muestra un aviso discreto;
2. lo retira de la cola y del estado visible;
3. avanza al siguiente archivo disponible;
4. solicita un reescaneo para sincronizar la biblioteca.

La caché no es una base de datos ni reemplaza los archivos. Reiniciar la aplicación
simplemente hace que se reconstruya.

## Límites actuales

- La respuesta admite hasta 2000 archivos. Para colecciones mayores se añadirá
  paginación/snapshot persistente sin cambiar los IDs actuales.
- Una foto de artista usa por ahora el cover representativo de uno de sus álbumes; no
  se descargan fotografías externas durante el escaneo.
- Las playlists `.m3u8` se conservan en disco, pero esta versión agrupa principalmente
  mediante tags y la carpeta `Playlists/`.
