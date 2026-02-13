"""Pydantic input models for MCP tool arguments."""

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field


class FetchRSSInput(BaseModel):
    """Input for feedder-mcp_fetch_rss tool."""

    opml_path: Optional[str] = Field(
        None, description="Path to OPML file with RSS feeds"
    )
    limit: Optional[int] = Field(None, description="Maximum number of papers to fetch")
    since: Optional[date] = Field(
        None, description="Only fetch papers published after this date (YYYY-MM-DD)"
    )


class FetchGmailInput(BaseModel):
    """Input for feedder-mcp_fetch_gmail tool."""

    query: Optional[str] = Field(None, description="Gmail search query")
    limit: Optional[int] = Field(None, description="Maximum number of papers to fetch")
    since: Optional[date] = Field(
        None, description="Only fetch papers from emails after this date"
    )


class FilterKeywordsInput(BaseModel):
    """Input for feedder-mcp_filter_keywords tool."""

    papers_json: str = Field(
        ..., description="JSON string of papers array to filter"
    )
    keywords: List[str] = Field(
        ..., description="Keywords to match (OR logic)"
    )
    exclude: Optional[List[str]] = Field(
        None, description="Keywords to exclude"
    )
    authors: Optional[List[str]] = Field(
        None, description="Author names to match (OR logic)"
    )
    min_date: Optional[date] = Field(
        None, description="Minimum publication date"
    )
    has_pdf: bool = Field(False, description="Require PDF availability")


class FilterAIInput(BaseModel):
    """Input for feedder-mcp_filter_ai tool."""

    papers_json: str = Field(
        ..., description="JSON string of papers array to filter"
    )
    research_prompt: Optional[str] = Field(
        None, description="Research interest prompt (uses config default if not set)"
    )


class EnrichInput(BaseModel):
    """Input for feedder-mcp_enrich tool."""

    papers_json: str = Field(
        ..., description="JSON string of papers array to enrich"
    )
    provider: str = Field(
        "all",
        description="Enrichment provider: 'crossref', 'openalex', or 'all'",
    )


class ExportJSONInput(BaseModel):
    """Input for feedder-mcp_export_json tool."""

    papers_json: str = Field(
        ..., description="JSON string of papers array to export"
    )
    filepath: str = Field(
        ..., description="Output file path"
    )
    include_metadata: bool = Field(
        True, description="Include metadata in export"
    )


class GenerateKeywordsInput(BaseModel):
    """Input for feedder-mcp_generate_keywords tool."""

    research_prompt: Optional[str] = Field(
        None,
        description="Research interest prompt (uses config default if not set)",
    )


class SearchCrossrefInput(BaseModel):
    """Input for feedder-mcp_search_crossref tool."""

    title: str = Field(..., description="Paper title to search for")


class SearchOpenalexInput(BaseModel):
    """Input for feedder-mcp_search_openalex tool."""

    title: str = Field(..., description="Paper title to search for")

