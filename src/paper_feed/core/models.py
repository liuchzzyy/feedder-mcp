"""Core data models for paper-feed."""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import date


class PaperItem(BaseModel):
    """Universal paper model (independent of Zotero).

    Attributes:
        title: Paper title
        authors: List of author names
        abstract: Paper abstract/summary
        published_date: Publication date
        doi: Digital Object Identifier (optional)
        url: Paper URL (optional, for flexibility with various sources)
        pdf_url: Direct link to PDF
        source: Source name (e.g., "arXiv", "Nature")
        source_id: Unique ID from source
        source_type: Source type ("rss" or "email")
        metadata: Additional source-specific data
    """

    title: str
    authors: List[str] = Field(default_factory=list)
    abstract: str = Field(default="")
    published_date: Optional[date] = None
    doi: Optional[str] = None  # DOI 可选字段
    url: Optional[str] = None  # Made optional for flexibility
    pdf_url: Optional[str] = None
    source: str
    source_id: Optional[str] = None
    source_type: str  # "rss" or "email"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FilterCriteria(BaseModel):
    """Filter criteria for paper selection.

    Attributes:
        keywords: Required keywords (OR logic)
        exclude_keywords: Keywords to exclude
        min_date: Earliest publication date
        authors: Required author names (OR logic)
        has_pdf: Require PDF availability
    """

    keywords: List[str] = Field(default_factory=list)
    exclude_keywords: List[str] = Field(default_factory=list)
    min_date: Optional[date] = None
    authors: List[str] = Field(default_factory=list)
    has_pdf: bool = False


class FilterResult(BaseModel):
    """Result of filtering operation.

    Attributes:
        papers: Papers that passed the filter
        total_count: Total papers before filtering
        passed_count: Papers that passed
        rejected_count: Papers that were rejected
        filter_stats: Detailed statistics
    """

    papers: List[PaperItem]
    total_count: int
    passed_count: int
    rejected_count: int
    filter_stats: Dict[str, Any] = Field(default_factory=dict)
