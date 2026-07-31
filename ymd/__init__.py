"""Core modules for YT-Descargar.

The legacy Flask entrypoint remains in :mod:`app_playlist` while reusable
services live here.  This keeps the current launcher compatible and lets the
application migrate incrementally instead of requiring a risky rewrite.
"""

from .version import VERSION

__version__ = VERSION
