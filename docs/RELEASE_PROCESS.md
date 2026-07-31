# Proceso de publicación

## Esquema de versiones

El proyecto usa una secuencia decimal de producto:

`0.012 → 0.013 → 0.014 → 0.015 → 0.016`

No se interpreta como SemVer estricto. La etiqueta Git siempre añade `v`, por
ejemplo `v0.012`. La versión vive en `ymd/version.py` y `pyproject.toml`.

## Lista de control

1. Actualizar versión, changelog y notas en `docs/releases/`.
2. Ejecutar pruebas, compilación, lint y smoke test.
3. Confirmar que no hay secretos, medios ni binarios grandes.
4. Revisar capturas para excluir rutas/nombres privados.
5. Crear rama `release/vX.XXX` o PR equivalente.
6. Exigir revisión de `@rafaeln0h`.
7. Integrar en `main` sólo con autorización.
8. Crear tag anotado `vX.XXX`.
9. Crear GitHub Release con notas, checksums y artefactos verificados.
10. Verificar enlaces, workflow y descarga limpia.

## Artefactos

v0.012 se publica como código fuente. No se debe adjuntar `ffmpeg.exe` sin
proceso explícito de licencias, procedencia y checksums. Los instaladores
firmados son un objetivo posterior.

## Reversión

No se mueve ni reemplaza un tag publicado. Ante un error:

- marcar la release con advertencia;
- corregir en la siguiente versión;
- retirar sólo artefactos inseguros conservando explicación y trazabilidad.

