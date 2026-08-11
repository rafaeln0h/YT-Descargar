# Roadmap 0.013–0.016

El orden puede cambiar después de pruebas y comentarios. Cada integración
requiere autorización de `@rafaeln0h`.

## 0.012 — base pública

- Versión, licencia, gobierno, plantillas, CI y documentación.
- Metadatos extendidos, procedencia y MusicBrainz incrustados en el archivo.
- Biblioteca local, minirreproductor, Range y logs.
- Investigación comercial/multiplataforma y contratos de capacidades.

## 0.013 — estabilidad y descargas

- Historial atómico y recuperación de tareas interrumpidas sin borrar medios.
- Reintento de tareas recuperadas y validación de archivos en múltiples álbumes.
- Diagnóstico de Python, yt-dlp, EJS, Deno/Node y FFmpeg desde la interfaz.
- Discografías verificadas de YouTube Music y organización configurable de sencillos.
- yt-dlp estable con dependencias recomendadas y selección automática de cliente.
- ZIP descargable, checksum SHA-256 y CI en Windows/Ubuntu.

## 0.014 — biblioteca y editor de metadatos

- Migrar cola, historial y configuración a SQLite con migraciones versionadas.
- Identidad de duplicados por extractor, ID y perfil, no sólo por filename.
- Reanudación por fragmentos cuando el extractor y el formato lo permitan.
- Editor individual/masivo con vista previa, diff, deshacer y retag.
- Caché y revisión manual de coincidencias MusicBrainz.
- Carátula/letra para más contenedores y `.lrc` sincronizado.
- Exportación M3U8/XSPF y ReplayGain/EBU R128 opcional.
- Capítulos y recorte seguro.

## 0.015 — escritorio multiplataforma

- Extraer dominio de descarga a módulos y API `/api/v1`.
- Cliente accesible, internacionalizable y empaquetado para
  Windows/Linux/macOS.
- Presets Plex/Jellyfin/Kodi, importación/exportación sin secretos.
- Instaladores, checksums, SBOM y firma donde sea posible.

## 0.016 — base móvil

- Cliente Android inicial o companion app.
- API autenticada para servidor personal.
- Modo iOS limitado a archivos propios/importados y proveedores autorizados.
- Sincronización opt-in, almacenamiento acotado y notificaciones.
- Pruebas de contrato entre motor y clientes.

## Guardas de aceptación

Cada versión debe incluir pruebas, changelog, documentación, logs sin secretos,
revisión de traversal/XSS/SSRF/comandos, migración de datos y validación con una
biblioteca representativa. Ninguna versión habilita DRM bypass ni acceso no
autorizado.
