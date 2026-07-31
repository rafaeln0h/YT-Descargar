# Política de seguridad

## Versiones soportadas

| Versión | Soporte |
|---|---|
| `0.012` | Sí |
| Anteriores | No |

La tabla se actualizará en cada publicación. Sólo la versión más reciente recibe
correcciones durante la etapa `0.x`.

## Reportar una vulnerabilidad

No abras un issue público con detalles explotables. Usa **Security advisories →
Report a vulnerability** en GitHub. Incluye versión, sistema operativo, impacto,
pasos mínimos, logs saneados y una corrección sugerida si la tienes.

El mantenedor acusará recibo cuando pueda, validará el hallazgo y coordinará
corrección y publicación. No se promete un SLA durante la etapa comunitaria.

## Límites del modelo actual

- Flask está diseñado para uso local de una persona, no como servicio público.
- Las cookies del navegador conceden acceso a sesiones del usuario.
- Los títulos, miniaturas, subtítulos y metadatos son datos externos no fiables.
- yt-dlp y FFmpeg procesan contenido complejo y deben mantenerse actualizados.
- La API de reproducción valida rutas, pero no implementa cuentas ni permisos.

Nunca publiques cookies, tokens, rutas personales, medios privados ni URLs de
stream firmadas en reportes.

