"""Paper data sources (RSS, Gmail, CrossRef, OpenAlex, etc.)."""

from paper_feed.sources.opml import OPMLParser, parse_opml
from paper_feed.sources.rss import RSSSource
from paper_feed.sources.rss_parser import RSSParser
from paper_feed.sources.gmail import GmailSource
from paper_feed.sources.gmail_parser import GmailParser
from paper_feed.sources.crossref import CrossrefClient
from paper_feed.sources.openalex import OpenAlexClient

__all__ = [
    "RSSSource",
    "RSSParser",
    "OPMLParser",
    "parse_opml",
    "GmailSource",
    "GmailParser",
    "CrossrefClient",
    "OpenAlexClient",
]
