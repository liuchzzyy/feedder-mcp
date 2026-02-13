"""Tool name enumeration for feedder-mcp MCP tools."""

from enum import Enum


class ToolName(str, Enum):
    """MCP tool names for feedder-mcp."""

    FETCH_RSS = "feedder-mcp_fetch_rss"
    FETCH_GMAIL = "feedder-mcp_fetch_gmail"
    FILTER_KEYWORDS = "feedder-mcp_filter_keywords"
    FILTER_AI = "feedder-mcp_filter_ai"
    ENRICH = "feedder-mcp_enrich"
    EXPORT_JSON = "feedder-mcp_export_json"
    GENERATE_KEYWORDS = "feedder-mcp_generate_keywords"
    SEARCH_CROSSREF = "feedder-mcp_search_crossref"
    SEARCH_OPENALEX = "feedder-mcp_search_openalex"

