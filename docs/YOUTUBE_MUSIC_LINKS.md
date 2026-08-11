# Enlaces de artista y discografía de YouTube Music

La aplicación distingue el alcance del enlace antes de descargar. Detectar no
inicia una descarga: primero presenta el contenido, aplica una selección segura
y espera que el usuario pulse **Descargar ahora** o **Agregar a cola**.

## Página completa del artista

Ejemplo: `https://music.youtube.com/@LillyGoodmanOficial`

Combina el catálogo musical oficial de YouTube Music con las playlists públicas
y el contenido del canal:

- álbumes, singles y EPs se consultan con `ytmusicapi` y conservan tipo, año,
  artista del álbum, cover y URL de la colección oficial;
- playlists se muestran como una categoría separada;
- videos del canal permanecen disponibles en el filtro **Canciones/videos**, pero
  no se seleccionan por defecto para evitar podcasts, shorts y duplicados;
- la vista inicial **Discografía** agrupa álbumes, EPs, singles y playlists.

## Sección de lanzamientos

Ejemplo: `https://music.youtube.com/browse/MPAD...`

Representa únicamente la sección oficial **Álbumes, singles y EPs**. No incluye
playlists ni videos del canal. Cada tarjeta muestra el artista real, año y tipo de
lanzamiento; ya no interpreta “Álbum”, “Sencillo” o “EP” como si fueran artistas.

## Descarga y organización

1. Pega el enlace y pulsa **Detectar**.
2. Revisa el resumen por categorías y usa **Álbumes**, **Singles**, **EPs**,
   **Playlists** o **Canciones/videos** para cambiar la selección.
3. Pulsa **Descargar ahora** para iniciar o **Agregar a cola** para guardar la
   tarea; en este último caso abre **Descargas** y pulsa **Iniciar cola**.
4. La pestaña Descargas muestra un contador y existe un aviso flotante mientras
   haya tareas activas. Los estados terminados o con error generan un aviso interno
   y, si el usuario dio permiso, una notificación del sistema.

Los lanzamientos oficiales se expanden pista por pista antes de descargar. La
estructura resultante es `Artista del álbum/Año - Álbum/01 - Canción.ext`. Se
preservan el tipo de lanzamiento y el año del catálogo como contexto; después,
cada pista pasa por la jerarquía normal de metadatos y sólo se completan campos
verificados. Un género ausente continúa vacío y se registra como faltante.

YouTube Music cambia sus respuestas con frecuencia. Si `ytmusicapi` no está
disponible, la aplicación usa un respaldo conservador y lo indica en el resumen.
