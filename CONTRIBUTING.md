# Contribuir a YT-Descargar

Gracias por ayudar. Se aceptan reportes, documentación, traducciones, pruebas y
código. Que una propuesta sea pública no implica su integración automática:
`@rafaeln0h` revisa y autoriza cada cambio.

## Antes de empezar

1. Busca un issue existente.
2. Para cambios grandes, abre primero una propuesta de diseño.
3. No incluyas medios descargados, cookies, tokens, rutas personales ni datos
   privados en commits, logs o capturas.
4. Trabaja sólo con contenido autorizado durante las pruebas.

## Entorno

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
ruff check app_playlist.py ymd tests
```

## Flujo de cambios

- Crea una rama descriptiva desde `main`.
- Mantén cada PR enfocada y explica problema, solución, riesgos y pruebas.
- Añade o actualiza pruebas para rutas, tags, seguridad y plantillas.
- Actualiza documentación y `CHANGELOG.md` si cambia el comportamiento visible.
- Usa commits claros, por ejemplo `feat(metadata): añadir MusicBrainz IDs`.
- Marca las casillas de la plantilla de PR.

## Reglas técnicas

- Los proveedores externos deben tener timeout, identificación, rate limit,
  caché y fallo independiente de la descarga principal.
- Nunca registres cookies, cabeceras de autorización, URLs firmadas ni query
  strings sensibles.
- Toda ruta recibida del cliente debe resolverse y validarse.
- La UI no debe insertar títulos externos como HTML sin escapar.
- Conserva compatibilidad con Python 3.10+.
- Las nuevas capacidades deben exponer su estado en
  `/api/system/capabilities` cuando sean relevantes para clientes.

## Licencia de contribuciones

Al enviar una contribución declaras que tienes derecho a hacerlo y aceptas que
se distribuya bajo la licencia `MIT`, la licencia del proyecto. No envíes código
copiado de programas comerciales ni de repositorios con licencias incompatibles.

Lee también [Código de conducta](CODE_OF_CONDUCT.md),
[Gobierno](GOVERNANCE.md) y [Seguridad](SECURITY.md).
