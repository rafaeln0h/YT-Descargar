# API local

Base predeterminada: `http://127.0.0.1:5000`.

La API de v0.012 no implementa autenticación y sólo debe exponerse en loopback.
No publiques el puerto en Internet.

## Diagnóstico

### `GET /api/system/health`

Devuelve salud, versión, canal, etiqueta de release, raíz de descargas, estado
del archivo anti-duplicados y ruta de logs.

### `GET /api/system/capabilities`

Contrato de descubrimiento para futuros clientes. Devuelve funciones, formatos,
contenedores etiquetables, fuentes de metadata y plataformas actuales/planeadas.
Los clientes deben probar capacidades; no inferirlas sólo por versión.

### `GET /api/system/logs?limit=200`

Devuelve entre 1 y 1000 líneas recientes. Los logs no deben contener secretos.

## Biblioteca

### `GET /api/library?limit=300&q=texto`

Escanea la raíz configurada y devuelve una lista limitada de medios. `q` busca
en nombre y ruta relativa.

### `GET /api/library/media/<media_id>`

Transmite un archivo con `Range`, ETag y validación de ruta. `media_id` es un
identificador opaco generado por la biblioteca; no es una ruta de filesystem.

## Evolución

Antes de acceso remoto o móvil se requiere:

- prefijo versionado (`/api/v1`);
- autenticación y revocación;
- CORS explícito;
- límites por tamaño/tasa;
- IDs persistentes de jobs;
- OpenAPI y pruebas de contrato.

