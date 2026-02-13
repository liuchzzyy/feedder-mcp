"""Core data models for feedder-mcp.

Contains PaperItem, FilterCriteria, FilterResult, and abstract base classes.
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PaperItem(BaseModel):
    """Universal paper model aligned with Zotero journalArticle schema."""

    # --- Core fields ---
    title: str
    source: str
    source_type: str  # "rss" or "email"

    # --- Bibliographic fields ---
    authors: List[str] = Field(default_factory=list)
    abstract: str = Field(default="")
    published_date: Optional[date] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    publication_title: Optional[str] = None
    journal_abbreviation: Optional[str] = None
    publisher: Optional[str] = None
    place: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    section: Optional[str] = None
    part_number: Optional[str] = None
    part_title: Optional[str] = None
    series: Optional[str] = None
    series_title: Optional[str] = None
    series_text: Optional[str] = None
    citation_key: Optional[str] = None
    access_date: Optional[date] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    issn: Optional[str] = None
    archive: Optional[str] = None
    archive_location: Optional[str] = None
    short_title: Optional[str] = None
    language: Optional[str] = None
    library_catalog: Optional[str] = None
    call_number: Optional[str] = None
    rights: Optional[str] = None
    item_type: str = "journalArticle"

    # --- Internal fields ---
    source_id: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class FilterCriteria(BaseModel):
    """Filter criteria for paper selection."""

    keywords: List[str] = Field(default_factory=list)
    exclude_keywords: List[str] = Field(default_factory=list)
    min_date: Optional[date] = None
    authors: List[str] = Field(default_factory=list)
    has_pdf: bool = False


class FilterResult(BaseModel):
    """Result of filtering operation."""

    papers: List[PaperItem]
    total_count: int
    passed_count: int
    rejected_count: int
    filter_stats: Dict[str, Any] = Field(default_factory=dict)


class PaperSource(ABC):
    """Abstract base class for paper data sources."""

    source_name: str = "base"
    source_type: str = "base"

    @abstractmethod
    async def fetch_papers(
        self, limit: Optional[int] = None, since: Optional[date] = None
    ) -> List[PaperItem]:
        pass


class ExportAdapter(ABC):
    """Abstract base class for export adapters."""

    @abstractmethod
    async def export(self, papers: List[PaperItem], **kwargs: Any) -> Any:
        pass


def format_papers_text(papers: List[PaperItem], max_papers: int = 50) -> str:
    """Format a list of papers as readable text for MCP responses.

    Args:
        papers: List of PaperItem objects.
        max_papers: Maximum papers to include in output.

    Returns:
        Formatted text string.
    """
    if not papers:
        return "No papers found."

    lines = [f"Found {len(papers)} papers:\n"]
    for i, paper in enumerate(papers[:max_papers]):
        lines.append(f"[{i}] {paper.title}")
        if paper.authors:
            lines.append(f"    Authors: {', '.join(paper.authors[:3])}")
        if paper.doi:
            lines.append(f"    DOI: {paper.doi}")
        if paper.published_date:
            lines.append(f"    Date: {paper.published_date}")
        if paper.source:
            lines.append(f"    Source: {paper.source} ({paper.source_type})")
        lines.append("")

    if len(papers) > max_papers:
        lines.append(f"... and {len(papers) - max_papers} more papers.")

    return "\n".join(lines)

