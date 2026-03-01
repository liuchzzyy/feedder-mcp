"""Fetch service wrapping RSS and Gmail sources."""

from datetime import date
from typing import List, Optional

from src.models.responses import PaperItem
from src.sources.gmail import GmailSource
from src.sources.rss import RSSSource


class FetchService:
    """Service for fetching papers from external sources."""

    async def fetch_rss(
        self,
        opml_path: Optional[str] = None,
        limit: Optional[int] = None,
        since: Optional[date] = None,
    ) -> List[PaperItem]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        source = RSSSource(opml_path=opml_path)
        return await source.fetch_papers(limit=limit, since=since)

    async def fetch_gmail(
        self,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        since: Optional[date] = None,
    ) -> List[PaperItem]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        source = GmailSource(query=query)
        return await source.fetch_papers(limit=limit, since=since)
