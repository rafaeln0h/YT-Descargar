# Arquitectura

## Estado actual

La aplicación original reúne configuración, extracción, cola, historial,
descarga, metadata, letras, portadas, API y servidor Flask en
`app_playlist.py`. La interfaz también tiene CSS y JavaScript extensos dentro de
las plantillas.

La modernización conserva el launcher y extrae primero los límites con mayor
beneficio y menor riesgo.

```text
Navegador
   |
   +-- UI existente (detección, cola, historial, ajustes)
   +-- mini-player.js (biblioteca y reproducción)
            |
Flask ------+--------------------------------------
   |        |                 |                   |
Descarga  ymd.routes      ymd.library         Diagnóstico
actual      |                 |
   |        +-- índice        +-- resolución segura
 yt-dlp     +-- streaming     +-- lectura de tags
   |
 FFmpeg --> ymd.metadata --> archivo final con tags
                 ^
                 |
         ymd.enrichment (MusicBrainz)
```

## Decisiones

### Migración incremental

No se reescribió el descargador completo. Una reescritura simultánea habría
puesto en riesgo detección de YouTube Music, cookies, reintentos, portadas y
plantillas. Los módulos nuevos tienen pruebas independientes y el monolito
puede reducirse por etapas.

### Streaming seguro

La API entrega identificadores Base64 URL-safe de rutas relativas. Al recibir
un identificador:

1. se decodifica;
2. se rechazan rutas absolutas y `..`;
3. se resuelve contra la raíz configurada;
4. se verifica que siga dentro de esa raíz;
5. se limita a extensiones multimedia conocidas.

Flask usa respuestas condicionales para soportar `Range` y búsqueda dentro del
audio/video.

### Etiquetado best-effort

La descarga es el resultado primario. Los tags avanzados, letras y portada se
aplican después; un proveedor externo caído se registra pero no destruye el
archivo válido.

La respuesta final de yt-dlp se filtra a un modelo neutral; no se copian URLs
firmadas. MusicBrainz se consulta con identificación, rate limit, caché y
coincidencia conservadora.

### Logs

`logs/ymd.log` rota a 2 MB con cinco copias. Incluye fecha, nivel, logger e hilo.
Los mensajes de yt-dlp ya no se descartan silenciosamente.

## Próximas fronteras

- `ymd/runtime.py`: detección de Deno/Node, diagnóstico y opciones comunes de yt-dlp.
- `ymd/downloader.py`: futura extracción de la ejecución que aún vive en `app_playlist.py`.
- `ymd/jobs.py`: máquina de estados y cancelación cooperativa.
- `ymd/storage.py`: SQLite para trabajos, historial, archivos y suscripciones.
- `ymd/enrichment/`: MusicBrainz, Cover Art Archive y letras con caché.
- `static/js/`: separar detector, cola, historial, ajustes y componentes.

La API pública debe permanecer estable durante esas migraciones.
