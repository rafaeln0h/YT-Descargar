# Diagnóstico de fallos

## La detección o descarga dejó de funcionar

1. Actualiza dependencias: `python -m pip install -U -r requirements.txt`.
2. Abre `http://localhost:5000/api/system/health`.
3. Revisa `logs/ymd.log` o `/api/system/logs?limit=300`.
4. Comprueba FFmpeg con `ffmpeg_portable\bin\ffmpeg.exe -version`.
5. Si el video requiere sesión, configura navegador y perfil en Ajustes.
6. Abre Configuración → Sistema → Diagnóstico del motor y confirma que
   `yt-dlp-ejs`, un runtime JavaScript y FFmpeg aparezcan disponibles.

No publiques cookies ni el contenido completo de perfiles del navegador.

## YouTube responde 403, 429 o pide inicio de sesión

- Reduce fragmentos concurrentes y añade intervalo entre solicitudes.
- Evita reintentos agresivos.
- Actualiza yt-dlp.
- Usa cookies solo desde un perfil que controles.
- Algunos formatos requieren un runtime JavaScript moderno; revisa el log de
  yt-dlp antes de cambiar clientes a ciegas.
- Conserva el cliente de YouTube en `auto`. No fuerces `web_music` sin un proveedor
  de PO Token: yt-dlp omitirá formatos afectados y puede recibir HTTP 403.
- Los PO Tokens manuales vinculados a un video no son una solución permanente.
  Si el modo automático continúa fallando, evalúa un proveedor recomendado por
  yt-dlp como plugin opcional y revisa primero su código y requisitos.

## “320 kbps” suena igual o peor

La fuente puede ser AAC/Opus de menor bitrate. La transcodificación no aumenta
la información. Prueba M4A u OPUS para evitar conversiones adicionales.

## El minirreproductor no muestra archivos

- Revisa `download_path` en Configuración.
- Pulsa **Actualizar** en Biblioteca.
- Confirma que la extensión esté soportada.
- La biblioteca no sale de la raíz configurada por diseño.

## Etiquetas faltantes

- WAV tiene compatibilidad desigual entre reproductores.
- Un valor detectado tiene prioridad sobre los defaults.
- MusicBrainz, Cover Art Archive o Deezer pueden fallar temporalmente; la
  descarga continúa y el fallo queda en el log.
