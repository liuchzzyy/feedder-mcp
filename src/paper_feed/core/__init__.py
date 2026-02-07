"""Core data models, base classes, and configuration."""

from paper_feed.core.base import ExportAdapter, PaperSource
from paper_feed.core.config import (
    get_crossref_config,
    get_gmail_config,
    get_openalex_config,
    get_openai_config,
    get_research_prompt,
    get_rss_config,
    get_zotero_config,
    reload_config,
)
from paper_feed.core.models import FilterCriteria, FilterResult, PaperItem

__all__ = [
    "PaperItem",
    "FilterCriteria",
    "FilterResult",
    "PaperSource",
    "ExportAdapter",
    "get_openai_config",
    "get_gmail_config",
    "get_zotero_config",
    "get_rss_config",
    "get_crossref_config",
    "get_openalex_config",
    "get_research_prompt",
    "reload_config",
]
