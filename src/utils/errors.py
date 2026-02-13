"""Custom exceptions and error formatting for feedder-mcp."""


class PaperFeedError(Exception):
    """Base exception for feedder-mcp."""


class SourceError(PaperFeedError):
    """Error fetching papers from a source."""


class FilterError(PaperFeedError):
    """Error during paper filtering."""


class EnrichError(PaperFeedError):
    """Error during paper enrichment."""


class ExportError(PaperFeedError):
    """Error during paper export."""


class ConfigError(PaperFeedError):
    """Error in configuration."""


def format_error(error: Exception) -> str:
    """Format an exception for MCP error responses.

    Args:
        error: The exception to format.

    Returns:
        Human-readable error message string.
    """
    error_type = type(error).__name__
    return f"{error_type}: {error}"

