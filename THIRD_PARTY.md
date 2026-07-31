# Dependencias y servicios de terceros

YT-Descargar se distribuye bajo MIT. Sus dependencias conservan sus propias
licencias; revisa los metadatos de cada paquete y los proyectos enlazados antes
de redistribuir un binario.

Dependencias principales:

- Flask y Flask-CORS
- yt-dlp
- FFmpeg/ffprobe (externos)
- Mutagen
- musicbrainzngs
- Pillow
- Requests

Servicios opcionales consultados durante la ejecución:

- MusicBrainz
- Cover Art Archive
- Deezer
- YouTube/YouTube Music

Consulta [docs/SOURCES.md](docs/SOURCES.md). Antes de publicar instaladores se
debe generar un SBOM, agrupar avisos/licencias aplicables y documentar el origen
y checksum de FFmpeg.

