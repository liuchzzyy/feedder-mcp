"""RSS feed source for paper collection."""

import asyncio
import logging
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import feedparser
import httpx

from src.config.settings import get_rss_config
from src.models.responses import PaperItem, PaperSource
from src.sources.opml import OPMLParser
from src.sources.rss_parser import RSSParser
from src.utils.dedup import deduplicate_papers, identity_keys_for_paper

logger = logging.getLogger(__name__)

def _dedup_key(paper: PaperItem) -> tuple[str, str] | None:
    keys = identity_keys_for_paper(paper)
    return keys[0] if keys else None


class RSSSource(PaperSource):
    """Paper source that reads RSS feeds from an OPML file."""

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

        if opml_path is None:
            opml_path = config.get("opml_path", "feeds/RSS_official.opml")

        self.opml_path = opml_path
        self.user_agent = user_agent or config.get("user_agent", "feedder-mcp/2.0")
        self.timeout = timeout if timeout is not None else config.get("timeout", 30)
        self.max_concurrent = (
            max_concurrent
            if max_concurrent is not None
            else config.get("max_concurrent", 10)
        )
        self._parser = RSSParser()

        opml = OPMLParser(self.opml_path)
        self._feeds: List[Dict[str, str]] = opml.parse()

        if not self._feeds:
            raise ValueError(f"No RSS feeds found in OPML file: {self.opml_path}")

        logger.info(
            f"RSSSource initialised with {len(self._feeds)} feeds from {self.opml_path}"
        )

    @property
    def feed_count(self) -> int:
        return len(self._feeds)

    @property
    def feeds(self) -> List[Dict[str, str]]:
        return list(self._feeds)

    async def fetch_papers(
        self,
        limit: Optional[int] = None,
        since: Optional[date] = None,
    ) -> List[PaperItem]:
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async def _fetch_one(feed: Dict[str, str]) -> List[PaperItem]:
                async with semaphore:
                    return await self._fetch_single_feed(
                        client=client,
                        feed_url=feed["url"],
                        source_name=feed.get("title")
                        or self._detect_source_name(feed["url"]),
                        since=since,
                    )

            tasks = [_fetch_one(f) for f in self._feeds]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        all_papers_raw: List[PaperItem] = []

        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                feed = self._feeds[i]
                logger.error(
                    f"Failed to fetch feed {feed.get('title', feed['url'])}: {result}"
                )
                continue

            all_papers_raw.extend(result)

        all_papers, dedup_stats = deduplicate_papers(all_papers_raw)
        logger.info(
            "RSS fetch dedup stats: input=%d, unique=%d, dropped=%d, by_key=%s",
            dedup_stats["input_count"],
            dedup_stats["unique_count"],
            dedup_stats["dropped_count"],
            dedup_stats["duplicates_by_key"],
        )

        if limit and len(all_papers) > limit:
            all_papers = all_papers[:limit]

        logger.info(
            f"Fetched {len(all_papers)} papers total from {len(self._feeds)} feeds"
        )
        return all_papers

    async def _fetch_single_feed(
        self,
        client: httpx.AsyncClient,
        feed_url: str,
        source_name: str,
        since: Optional[date] = None,
    ) -> List[PaperItem]:
        papers: List[PaperItem] = []

        try:
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
        meta: Dict[str, Any] = {}
        feed_obj = getattr(feed, "feed", None)
        if feed_obj:
            for key in ("title", "subtitle", "language"):
                val = getattr(feed_obj, key, None)
                if val:
                    meta[key] = str(val)
        version = getattr(feed, "version", None)
        if version:
            meta["version"] = str(version)
        encoding = getattr(feed, "encoding", None)
        if encoding:
            meta["encoding"] = str(encoding)
        return meta

    @staticmethod
    def _detect_source_name(url: str) -> str:
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

