"""Core data models for paper-feed."""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import date


class PaperItem(BaseModel):
    """Universal paper model aligned with Zotero journalArticle schema.

    Core fields (required):
        title: Paper title
        source: Source name (e.g., "arXiv", "Nature")
        source_type: Source type ("rss" or "email")

    Bibliographic fields (optional):
        authors: List of author names
        abstract: Paper abstract/summary
        published_date: Publication date
        doi: Digital Object Identifier
        url: Paper URL
        pdf_url: Direct link to PDF
        publication_title: Journal / publication name
        journal_abbreviation: Journal abbreviation
        publisher: Publisher name
        place: Place of publication
        volume: Journal volume
        issue: Journal issue number
        pages: Page range (e.g., "123-145")
        section: Article section
        part_number: Part number
        part_title: Part title
        series: Series name
        series_title: Series title
        series_text: Series text
        citation_key: Citation key for reference managers
        access_date: Date the resource was accessed
        pmid: PubMed ID
        pmcid: PubMed Central ID
        issn: ISSN of the journal
        archive: Archive name
        archive_location: Location in archive
        short_title: Abbreviated title
        language: Language of the paper
        library_catalog: Library catalog source
        call_number: Call number
        rights: License / copyright info
        item_type: Item type (e.g., "journalArticle", "conferencePaper")

    Internal fields:
        source_id: Unique ID from source
        extra: Additional data (enrichment metadata, feed info, etc.)
    """

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
