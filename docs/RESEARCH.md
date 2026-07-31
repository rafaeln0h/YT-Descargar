# Investigación comparativa

Fecha de corte: 31 de julio de 2026.

## Alcance y método

No existe una forma honesta de afirmar que se revisó literalmente “todo
GitHub”: hay millones de repositorios, proyectos privados y resultados que
cambian cada día. Se hizo una búsqueda amplia y reproducible con GitHub Search
por los temas `youtube-downloader`, `yt-dlp`, `youtube-music-downloader` y
combinaciones de “music metadata downloader”. Se priorizaron proyectos activos,
con uso visible o con una idea diferenciadora. También se revisaron las seis
referencias iniciales.

## Proyectos principales

| Proyecto | Qué aporta | Qué adoptar |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Motor activo, miles de extractores, postprocesadores, metadata y plugins | Mantenerlo como motor aislado y actualizable |
| [youtube-dl](https://github.com/ytdl-org/youtube-dl) | Base histórica y compatibilidad | Referencia, no motor principal |
| [YoutubeDownloader](https://github.com/Tyrrrz/YoutubeDownloader) | Separación Core/UI, búsqueda, formatos, autenticación | Frontera clara entre motor y presentación |
| [Arroxy](https://github.com/antonio-orionus/Arroxy) | UI multilingüe, 4K/HDR, playlists, privacidad | Perfiles sencillos y diagnóstico de dependencias |
| [ytDownloader](https://github.com/aandrew-me/ytDownloader) | Escritorio multiplataforma, selección por rango, compresión | Rango/recorte como fase posterior |
| [youtube-downloader](https://github.com/shohan-001/youtube-downloader) | Flujo Flask sencillo, VPS y selección de playlist | Mantener una ruta de uso simple |
| [MeTube](https://github.com/alexta69/metube) | Cola persistente, suscripciones y estado separado | Persistir cola y separar temporales |
| [YTSage](https://github.com/oop7/YTSage) | Tabla de formatos, SponsorBlock, capítulos, EBU R128, updater | Normalización, capítulos y comprobador de herramientas |
| [spotDL](https://github.com/spotDL/spotify-downloader) | Matching musical, guardar/sincronizar metadata, letras y portadas | Separar descarga de enriquecimiento y permitir retag |
| [yubal](https://github.com/guillevc/yubal) | YouTube Music, deduplicación por pista, M3U, sync, LRC | Identidad canónica y playlists sin duplicar archivos |
| [Pinchflat](https://github.com/kieraneglin/pinchflat) | Suscripciones, reglas, nombres flexibles, Plex/Jellyfin/Kodi | Presets de biblioteca y automatización |
| [ytdl-sub](https://github.com/jmbannon/ytdl-sub) | Metadata/plantillas altamente configurables y NFO | Motor declarativo de plantillas |
| [Seal](https://github.com/JunkFood02/Seal) | Plantillas de comandos y Mutagen en Android | Presets exportables sin exponer shell libre |
| [YTDLnis](https://github.com/deniscerri/ytdlnis) | Edición por elemento, horarios, cola concurrente, cookies | Edición masiva y por pista |
| [MyTube](https://github.com/franklioxygen/MyTube) | Descargador + reproductor + colecciones | Biblioteca y reproducción integradas |
| [Open Video Downloader](https://github.com/jely2002/youtube-dl-gui) | Tauri/Vue, audio, subtítulos y metadata | Experiencia multiplataforma y empaquetado |
| [Tartube](https://github.com/axcore/tartube) | Gestión avanzada de canales y archivos | Supervisión a gran escala |
| [Cobalt](https://github.com/imputnet/cobalt) | Interfaz mínima, API clara, foco en privacidad | Flujo principal corto y predecible |
| [Youtarr](https://github.com/DialmasterOrg/Youtarr) | Automatización y salida para centros multimedia | Suscripciones y reconciliación futura |
| [Tube Archivist](https://github.com/tubearchivist/tubearchivist) | Archivo, búsqueda, indexación y reproducción | Índice persistente cuando la biblioteca crezca |

## Programas y productos fuera de GitHub

- 4K Video Downloader: buenos presets y pegado de URL con pocas decisiones.
- JDownloader: fuerte en cola, reconexión, límites y extensiones.
- MediaHuman YouTube to MP3: experiencia musical simple y seguimiento de
  playlists.
- MusicBee, Kid3 y Mp3tag: referencia para edición por lotes, vista previa,
  ReplayGain y consistencia de etiquetas.
- Plex, Jellyfin, Kodi y VLC: consumidores reales que obligan a mantener nombres,
  carátulas, números de pista/disco y MIME correctos.

No se copió código de estos productos o repositorios. Se estudiaron patrones de
producto y arquitectura.

## Hallazgos aplicados

1. **El motor no debe ser la aplicación.** `yt-dlp` cambia con frecuencia; la UI
   debe depender de una interfaz controlada.
2. **Descarga y metadata son pasos distintos.** Un archivo válido no debe
   marcarse como fallido porque falle MusicBrainz, la portada o una letra.
3. **La ruta real es parte del resultado.** Guardar solo la carpeta impide
   reproducir, validar o retaggear una pista concreta.
4. **La biblioteca necesita límites de seguridad.** Nunca se debe aceptar una
   ruta arbitraria del navegador para `send_file`.
5. **Una cola en memoria no basta.** Es aceptable para esta iteración, pero la
   próxima migración debe usar SQLite y recuperación tras reinicio.
6. **“MP3 320 kbps” no crea calidad inexistente.** Transcodificar una fuente
   menor no agrega información. La UI debe mostrar fuente y salida por separado.
7. **YouTube bloquea y cambia.** Cookies, clientes, Deno/JS runtime, rate limits
   y actualizaciones del extractor requieren diagnóstico visible.

