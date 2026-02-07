"""paper-feed: Academic paper collection framework."""

__version__ = "1.0.0"

# Core exports
from paper_feed.core.base import ExportAdapter, PaperSource
from paper_feed.core.models import FilterCriteria, FilterResult, PaperItem

# Source implementations
from paper_feed.sources import RSSSource, GmailSource
from paper_feed.sources.crossref import CrossrefClient
from paper_feed.sources.openalex import OpenAlexClient

# AI module
from paper_feed.ai import KeywordGenerator

# Filter implementations (includes AIFilterStage)
from paper_feed.filters import AIFilterStage, FilterPipeline

# Adapter implementations
from paper_feed.adapters import JSONAdapter

try:
    from paper_feed.adapters import ZoteroAdapter

    _zotero_available = True
except ImportError:
    ZoteroAdapter = None  # type: ignore[assignment]
    _zotero_available = False

__all__ = [
    "PaperItem",
    "FilterCriteria",
    "FilterResult",
    "PaperSource",
    "ExportAdapter",
    "RSSSource",
    "GmailSource",
    "CrossrefClient",
    "OpenAlexClient",
    "FilterPipeline",
    "AIFilterStage",
    "KeywordGenerator",
    "JSONAdapter",
    "ZoteroAdapter",
]
