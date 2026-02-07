"""RSS feed source for paper collection.

RSSSource reads feeds exclusively from OPML files. It parses the OPML to
discover all RSS feed URLs, then fetches them concurrently and aggregates
the results into a single list of PaperItem objects.
"""

import asyncio
import logging
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import feedparser
import httpx

from paper_feed.core.base import PaperSource
from paper_feed.core.config import get_rss_config
from paper_feed.core.models import PaperItem
from paper_feed.sources.opml import OPMLParser
from paper_feed.sources.rss_parser import RSSParser

logger = logging.getLogger(__name__)


class RSSSource(PaperSource):
    """Paper source that reads RSS feeds from an OPML file.

    All feeds listed in the OPML are fetched concurrently; results are
    aggregated and deduplicated (by URL) into a single list.

    Args:
        opml_path: Path to OPML file. Falls back to the ``PAPER_FEED_OPML``
            environment variable, then to ``feeds/RSS_official.opml``.
        user_agent: HTTP User-Agent header for requests.
        timeout: Per-feed request timeout in seconds.
        max_concurrent: Maximum number of feeds to fetch in parallel.

    Raises:
        FileNotFoundError: If the resolved OPML file does not exist.
        ValueError: If the OPML file contains no valid RSS feeds.

    Example::

        source = RSSSource("feeds/RSS_official.opml")
        papers = await source.fetch_papers(limit=100)
    """

    source_name: str = "rss"
    source_type: str = "rss"

    def __init__(
        self,
        opml_path: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: Optional[int] = None,
        max_concurrent: Optional[int] = None,
    ):
        config = get_rss_config()

        # Resolve OPML path: explicit > env var > default
        if opml_path is None:
            opml_path = config.get("opml_path", "feeds/RSS_official.opml")

        self.opml_path = opml_path
        self.user_agent = user_agent or config.get("user_agent", "paper-feed/1.0")
        self.timeout = timeout if timeout is not None else config.get("timeout", 30)
        self.max_concurrent = (
            max_concurrent
            if max_concurrent is not None
            else config.get("max_concurrent", 10)
        )
        self._parser = RSSParser()

        # Parse OPML immediately so errors surface at construction time
        opml = OPMLParser(self.opml_path)
        self._feeds: List[Dict[str, str]] = opml.parse()

        if not self._feeds:
            raise ValueError(f"No RSS feeds found in OPML file: {self.opml_path}")

        logger.info(
            f"RSSSource initialised with {len(self._feeds)} feeds from {self.opml_path}"
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def feed_count(self) -> int:
        """Number of RSS feeds loaded from the OPML file."""
        return len(self._feeds)

    @property
    def feeds(self) -> List[Dict[str, str]]:
        """List of feed dicts (url, title, html_url, category)."""
        return list(self._feeds)

    # ------------------------------------------------------------------
    # PaperSource interface
    # ------------------------------------------------------------------

    async def fetch_papers(
        self,
        limit: Optional[int] = None,
        since: Optional[date] = None,
    ) -> List[PaperItem]:
        """Fetch papers from all RSS feeds in the OPML file.

        Feeds are fetched concurrently (up to *max_concurrent* at a time).
        Results are aggregated and deduplicated by URL.

        Args:
            limit: Maximum total number of papers to return.
            since: Only include papers published on or after this date.

        Returns:
            Deduplicated list of ``PaperItem`` objects.
        """
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def _fetch_one(feed: Dict[str, str]) -> List[PaperItem]:
            async with semaphore:
                return await self._fetch_single_feed(
                    feed_url=feed["url"],
                    source_name=feed.get("title")
                    or self._detect_source_name(feed["url"]),
                    since=since,
                )

        tasks = [_fetch_one(f) for f in self._feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate, skipping failed feeds
        all_papers: List[PaperItem] = []
        seen_urls: set[str] = set()

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                feed = self._feeds[i]
                logger.error(
                    f"Failed to fetch feed {feed.get('title', feed['url'])}: {result}"
                )
                continue

            for paper in result:
                # Deduplicate by URL
                key = paper.url or paper.title
                if key and key not in seen_urls:
                    seen_urls.add(key)
                    all_papers.append(paper)

        # Apply global limit after aggregation
        if limit and len(all_papers) > limit:
            all_papers = all_papers[:limit]

        logger.info(
            f"Fetched {len(all_papers)} papers total from {len(self._feeds)} feeds"
        )
        return all_papers

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_single_feed(
        self,
        feed_url: str,
        source_name: str,
        since: Optional[date] = None,
    ) -> List[PaperItem]:
        """Fetch and parse a single RSS feed.

        Args:
            feed_url: URL of the RSS feed.
            source_name: Human-readable name for this feed.
            since: Date filter (papers before this date are skipped).

        Returns:
            List of parsed ``PaperItem`` objects.
        """
        papers: List[PaperItem] = []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    feed_url,
                    headers={"User-Agent": self.user_agent},
                    follow_redirects=True,
                )
                response.raise_for_status()
                feed_content = response.text

            feed = await asyncio.to_thread(feedparser.parse, feed_content)

            if hasattr(feed, "bozo") and feed.bozo:
                logger.warning(
                    f"Potential issue parsing feed {feed_url}: "
                    f"{getattr(feed, 'bozo_exception', 'Unknown error')}"
                )

            # Extract feed-level metadata for enrichment
            feed_meta = self._extract_feed_meta(feed)

            entries = getattr(feed, "entries", [])
            logger.debug(f"Fetched {len(entries)} entries from {source_name}")

            for entry in entries:
                try:
                    paper = self._parser.parse(entry, source_name, feed_meta=feed_meta)

                    if since and paper.published_date:
                        if paper.published_date < since:
                            continue

                    papers.append(paper)

                except ValueError as e:
                    logger.warning(f"Skipping invalid entry from {source_name}: {e}")
                except Exception as e:
                    logger.error(
                        f"Error parsing entry from {source_name}: {e}",
                        exc_info=True,
                    )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching {feed_url}: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"Request error fetching {feed_url}: {e}")
        except Exception as e:
            logger.error(
                f"Unexpected error fetching from {source_name}: {e}",
                exc_info=True,
            )

        return papers

    @staticmethod
    def _extract_feed_meta(feed: Any) -> Dict[str, Any]:
        """Extract feed-level metadata from a parsed feed.

        Captures the feed's title, subtitle, language, version, and
        encoding when available. This metadata is passed to the parser
        so it can be stored in ``PaperItem.metadata``.

        Args:
            feed: Parsed feedparser feed object.

        Returns:
            Dict with available feed-level metadata.
        """
        meta: Dict[str, Any] = {}
        feed_obj = getattr(feed, "feed", None)
        if feed_obj:
            for key in ("title", "subtitle", "language"):
                val = getattr(feed_obj, key, None)
                if val:
                    meta[key] = str(val)
        # version and encoding are on the top-level feed object
        version = getattr(feed, "version", None)
        if version:
            meta["version"] = str(version)
        encoding = getattr(feed, "encoding", None)
        if encoding:
            meta["encoding"] = str(encoding)
        return meta

    @staticmethod
    def _detect_source_name(url: str) -> str:
        """Detect a human-readable source name from a feed URL.

        Args:
            url: RSS feed URL.

        Returns:
            Detected source name (e.g. "arXiv", "Nature").
        """
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()

        _KNOWN: Dict[str, str] = {
            "arxiv.org": "arXiv",
            "biorxiv.org": "bioRxiv",
            "medrxiv.org": "medRxiv",
            "nature.com": "Nature",
            "science.org": "Science",
            "pnas.org": "PNAS",
            "acs.org": "ACS",
            "rsc.org": "RSC",
            "springer.com": "Springer",
            "springernature.com": "Springer",
            "wiley.com": "Wiley",
            "elsevier.com": "Elsevier",
            "cell.com": "Cell",
            "sciencedirect.com": "ScienceDirect",
        }

        for domain, name in _KNOWN.items():
            if domain in netloc:
                return name

        return netloc.replace("www.", "").split(".")[0].capitalize()
