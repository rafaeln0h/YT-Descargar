# Comparativa con productos comerciales

Revisión de productos externos: 2026-07-31. Estado de YT-Descargar actualizado
para v0.013. Fuente primaria:
[páginas oficiales](SOURCES.md#productos-comerciales-comparados).

| Capacidad | YT-Descargar 0.013 | SnapDownloader | 4K Video Downloader+ | MediaHuman | iTubeGo |
|---|---:|---:|---:|---:|---:|
| Cola y descargas múltiples | Sí | Sí | Sí | Sí | Sí |
| Playlists/canales | Sí | Sí | Sí | Sí | Sí |
| Audio y video | Sí | Sí | Sí | Sí | Sí |
| Subtítulos | Sí | Sí | Sí | Sí | Sí |
| Metadatos musicales | Avanzados | Sí | Parcial | ID3 | Sí |
| Minirreproductor/biblioteca | Sí | Vista previa | Reproductor | Seguimiento | Reproductor |
| Programador | No | Sí | No documentado | Seguimiento | No documentado |
| Recorte | No | Sí | No documentado | No documentado | Sí |
| Navegador integrado | No | Sí | Sí | No | Sí |
| Código abierto | Sí | No | No | No | No |
| API local documentada | Sí | No documentada | No documentada | No documentada | No documentada |

“No documentado” significa que no apareció claramente en la página oficial
consultada; no demuestra ausencia.

## Qué conviene adoptar

### Prioridad inmediata

- Editor de metadatos con vista previa y confirmación de coincidencias.
- Administrador de cola persistente con reanudar, prioridad y reintento por item.
- Historial más visual con filtros, errores accionables y botón de reparación.
- Presets accesibles para audio, video, subtítulos y dispositivos.
- Diagnóstico de FFmpeg, yt-dlp, cookies y permisos desde la UI.

### Siguientes versiones

- Programador local y límites de velocidad/concurrencia.
- Selección y exportación de capítulos.
- Recorte sin recodificar cuando el contenedor lo permita.
- Perfiles por biblioteca y sincronización opcional.
- Importación/exportación de configuración sin secretos.

### No copiar

- No clonar nombres, textos, iconos, capturas ni diseño distintivo.
- No prometer “todos los sitios” o calidad que el origen no ofrece.
- No integrar bypass de DRM o controles de acceso.
- No recopilar telemetría por defecto para imitar productos comerciales.

La ventaja buscada no es tener más botones: es una herramienta local,
auditables, accesible, con metadatos trazables y recuperación clara de fallos.
