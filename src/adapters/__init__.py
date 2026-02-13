"""Export adapters for feedder-mcp."""

from src.adapters.json import JSONAdapter

try:
    from src.adapters.zotero import ZoteroAdapter

    _zotero_available = True
except ImportError:
    ZoteroAdapter = None  # type: ignore[assignment]
    _zotero_available = False

__all__ = ["JSONAdapter", "ZoteroAdapter"]

