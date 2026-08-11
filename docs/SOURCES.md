# Fuentes, referencias y atribuciones

Última revisión: 2026-08-10.

Este archivo documenta de dónde provino la investigación funcional. Los enlaces
sirven como referencia; no se copió código ni material visual de programas
comerciales.

## Motor y proyectos de código abierto

| Proyecto | Uso en la investigación |
|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Motor, postprocesadores, metadatos y compatibilidad de sitios |
| [yt-dlp-ejs](https://github.com/yt-dlp/ejs) | Scripts oficiales para resolver los desafíos JavaScript de YouTube |
| [Deno](https://deno.com/) | Runtime JavaScript recomendado por yt-dlp |
| [curl-cffi](https://github.com/lexiforest/curl_cffi) | Compatibilidad de red e impersonación TLS usada por yt-dlp |
| [youtube-dl](https://github.com/ytdl-org/youtube-dl) | Antecedente histórico del ecosistema |
| [YoutubeDownloader](https://github.com/Tyrrrz/YoutubeDownloader) | UX de escritorio, selección de streams y capítulos |
| [Arroxy](https://github.com/antonio-orionus/Arroxy) | Interfaz web y flujo de descarga |
| [ytdownloader](https://github.com/aandrew-me/ytdownloader) | Empaquetado de una GUI multiplataforma |
| [youtube-downloader](https://github.com/shohan-001/youtube-downloader) | Flujo simple de entrada y descarga |
| [MeTube](https://github.com/alexta69/metube) | Cola web, contenedores y operación local |
| [YTSage](https://github.com/oop7/YTSage) | GUI moderna alrededor de yt-dlp |
| [spotDL](https://github.com/spotDL/spotify-downloader) | Coincidencia y normalización de metadatos musicales |
| [yubal](https://github.com/edavalosanaya/yubal) | Biblioteca y reproducción local |

Revisar una función no significa que YT-Descargar adopte la licencia, marca o
código de ese proyecto. Antes de reutilizar código debe verificarse su licencia.

## Productos comerciales comparados

| Producto | Página oficial consultada |
|---|---|
| SnapDownloader | [Funciones](https://snapdownloader.com/features) |
| 4K Video Downloader Plus | [Producto](https://www.4kdownload.com/products/videodownloader) y [funciones premium](https://www.4kdownload.com/premium) |
| MediaHuman YouTube Downloader | [Producto](https://www.mediahuman.com/youtube-video-downloader/) |
| iTubeGo | [Producto](https://itubego.com/) y [Android](https://itubego.com/youtube-downloader-for-android/) |

Precios, límites y disponibilidad cambian. La comparativa conserva capacidades,
no precios.

## Metadatos y carátulas

- [MusicBrainz API](https://musicbrainz.org/doc/MusicBrainz_API)
- [MusicBrainz Search](https://musicbrainz.org/doc/MusicBrainz_API/Search)
- [Cover Art Archive API](https://musicbrainz.org/doc/Cover_Art_Archive/API)
- [Mutagen](https://mutagen.readthedocs.io/)
- [Deezer API](https://developers.deezer.com/api)
- [LRCLIB API](https://lrclib.net/docs)

MusicBrainz exige identificación del cliente y límites de uso. YT-Descargar usa
un `User-Agent`, espera entre solicitudes, aplica caché y sólo acepta
coincidencias fuertes. Los datos de terceros siguen sujetos a sus términos.

Para letras, la aplicación prueba primero captions de YouTube. Si no existen,
LRCLIB recibe artista, título, álbum y duración. El cliente se identifica,
consulta secuencialmente, espera entre solicitudes y respeta `Retry-After`.

## Plataformas y distribución

- [Apple App Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
- [Android Developers](https://developer.android.com/)
- [F-Droid inclusion policy](https://f-droid.org/docs/Inclusion_Policy/)
- [Tauri](https://tauri.app/)
- [Flutter](https://flutter.dev/)

Apple exige autorización para guardar, convertir o descargar medios de terceros.
El diseño iOS debe limitarse a contenido propio, autorizado o importado
localmente, y documentar los permisos del proveedor.

## Uso y términos

- [YouTube Terms of Service](https://www.youtube.com/static?template=terms)
- [FFmpeg legal](https://ffmpeg.org/legal.html)
- [FFmpeg downloads](https://ffmpeg.org/download.html)

Cada usuario es responsable de permisos, licencias, términos y leyes aplicables.
