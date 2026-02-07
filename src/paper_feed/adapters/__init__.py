"""Export adapters for paper-feed.

This module provides adapters for exporting PaperItem objects to various
destinations (JSON files, Zotero libraries, etc.).
"""

from paper_feed.adapters.json import JSONAdapter

# Try to import ZoteroAdapter (optional dependency)
try:
    from paper_feed.adapters.zotero import ZoteroAdapter

    _zotero_available = True
except ImportError:
    ZoteroAdapter = None  # type: ignore[assignment]
    _zotero_available = False

__all__ = ["JSONAdapter", "ZoteroAdapter"]
