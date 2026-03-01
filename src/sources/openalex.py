"""OpenAlex API client for academic metadata lookup and enrichment."""

import asyncio
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from src.config.settings import get_openalex_config
from src.models.responses import PaperItem
from src.utils.dedup import normalize_doi
from src.utils.text import DOI_PATTERN, clean_abstract

logger = logging.getLogger(__name__)
_DEFAULT_USER_AGENT = (
    "feedder-mcp/2.0 (https://github.com/feedder-mcp; mailto:{email})"
)


def _clean_doi(doi: str) -> str:
    normalized = normalize_doi(doi)
    if normalized:
        return normalized
    return doi.strip()


def _reconstruct_abstract(
    inverted_index: Optional[Dict[str, List[int]]],
) -> Optional[str]:
    if not inverted_index:
        return None

    try:
        word_positions: List[tuple] = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort(key=lambda x: x[0])
        text = " ".join(wp[1] for wp in word_positions)
        return clean_abstract(text)
    except Exception:
        return None


def _extract_doi_from_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = DOI_PATTERN.search(value)
    if match:
        return match.group(0)
    return None


@dataclass
class OpenAlexWork:
    """Represents a work (article) from OpenAlex API."""

    doi: str = ""
    title: str = ""
    authors: List[str] = field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[int] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    abstract: Optional[str] = None
    url: Optional[str] = None
    item_type: str = "journalArticle"
    cited_by_count: Optional[int] = None
    concepts: List[str] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "OpenAlexWork":
        doi_url = data.get("doi", "") or ""
        doi = doi_url.split("doi.org/")[-1] if "doi.org/" in doi_url else ""

        title = data.get("title", "") or data.get("display_name", "") or ""

        authors: List[str] = []
        for authorship in data.get("authorships", []):
            author_data = authorship.get("author", {})
            name = author_data.get("display_name", "")
            if name:
                authors.append(name)

        journal = None
        primary_location = data.get("primary_location") or {}
        if primary_location:
            source = primary_location.get("source") or {}
            if source:
                journal = source.get("display_name")

        year = data.get("publication_year")

        biblio = data.get("biblio") or {}
        volume = biblio.get("volume")
        issue = biblio.get("issue")
        first_page = biblio.get("first_page")
        last_page = biblio.get("last_page")
        pages = None
        if first_page and last_page:
            pages = f"{first_page}-{last_page}"
        elif first_page:
            pages = first_page

        abstract = _reconstruct_abstract(data.get("abstract_inverted_index"))
        url = data.get("doi") or data.get("id")

        openalex_type = data.get("type", "")
        type_mapping = {
            "article": "journalArticle",
            "book": "book",
            "book-chapter": "bookSection",
            "dissertation": "thesis",
            "proceedings": "conferencePaper",
            "proceedings-article": "conferencePaper",
            "report": "report",
            "dataset": "dataset",
        }
        item_type = type_mapping.get(openalex_type, "journalArticle")

        cited_by_count = data.get("cited_by_count")
        if cited_by_count == 0:
            cited_by_count = None

        concepts: List[str] = []
        for concept in data.get("concepts", []):
            if isinstance(concept, dict) and concept.get("score", 0) > 0.3:
                name = concept.get("display_name", "")
                if name:
                    concepts.append(name)

        return cls(
            doi=doi,
            title=title,
            authors=authors,
            journal=journal,
            year=year,
            volume=volume,
            issue=issue,
            pages=pages,
            abstract=abstract,
            url=url,
            item_type=item_type,
            cited_by_count=cited_by_count,
            concepts=concepts,
            raw_data=data,
        )


class OpenAlexClient:
    """Async client for querying the OpenAlex API."""

    def __init__(self, email: Optional[str] = None) -> None:
        config = get_openalex_config()
        if email is None:
            email = config.get("email")
        self.email = email
        self._api_key: Optional[str] = config.get("api_key")
        self._api_base: str = config.get("api_base", "https://api.openalex.org")
        self._timeout: float = config.get("timeout", 45.0)
        configured_user_agent = config.get("user_agent")
        if not isinstance(configured_user_agent, str):
            configured_user_agent = ""
        configured_user_agent = configured_user_agent.strip()
        if not configured_user_agent or configured_user_agent.isdigit():
            configured_user_agent = _DEFAULT_USER_AGENT
        self._user_agent_template = configured_user_agent
        self._max_rps: int = int(config.get("max_requests_per_second", 10) or 10)
        if self._api_key:
            logger.info("OpenAlex API key detected; requests will include api_key.")
        else:
            logger.warning(
                "OpenAlex API key is not configured; requests may hit tighter rate limits (429)."
            )
        if os.getenv("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
            self._min_interval = 0.0
        else:
            self._min_interval: float = 1.0 / max(self._max_rps, 1)
        self._last_request_at: float = 0.0
        self._rate_lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def _headers(self) -> Dict[str, str]:
        contact_email = self.email or "noreply@example.com"
        try:
            ua = self._user_agent_template.format(email=contact_email)
        except Exception:
            ua = _DEFAULT_USER_AGENT.format(email=contact_email)

        if "feedder-mcp" not in ua.lower():
            ua = f"feedder-mcp/2.0 {ua}".strip()
        if "mailto:" not in ua.lower():
            ua = f"{ua} (mailto:{contact_email})"

        headers = {"User-Agent": ua}
        if self.email:
            headers["mailto"] = self.email
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._api_base,
                headers=self._headers,
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _apply_rate_limit(self) -> None:
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_at = time.monotonic()

    @staticmethod
    def _retry_delay_seconds(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            if retry_after.isdigit():
                return float(retry_after)
            try:
                retry_dt = parsedate_to_datetime(retry_after)
                return max(0.0, retry_dt.timestamp() - time.time())
            except Exception:
                pass
        reset = response.headers.get("X-RateLimit-Reset")
        if reset and reset.isdigit():
            reset_at = float(reset)
            return max(0.0, reset_at - time.time())
        return min(4.0, 2 ** max(attempt - 1, 0))

    async def _get_with_retry(self, url: str, params: Dict[str, Any]) -> httpx.Response:
        client = await self._get_client()
        if self._api_key:
            params = dict(params)
            params["api_key"] = self._api_key

        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                await self._apply_rate_limit()
                response = await client.get(url, params=params)
                status_code = response.status_code
                if isinstance(status_code, int) and status_code == 429:
                    if attempt == max_attempts:
                        response.raise_for_status()
                    delay = self._retry_delay_seconds(response, attempt)
                    logger.warning("OpenAlex rate limited (429). Sleeping %.2fs", delay)
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                if isinstance(status_code, int) and status_code >= 500 and attempt < max_attempts:
                    delay = self._retry_delay_seconds(response, attempt)
                    await asyncio.sleep(delay)
                    continue
                raise
            except httpx.RequestError as exc:
                if attempt < max_attempts:
                    delay = min(4.0, 2 ** max(attempt - 1, 0))
                    logger.warning(
                        "OpenAlex transport error (%s). Retrying in %.2fs",
                        type(exc).__name__,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
        raise httpx.HTTPError("OpenAlex request failed")

    async def search_by_title(
        self,
        title: str,
        per_page: int = 5,
    ) -> List[OpenAlexWork]:
        try:
            response = await self._get_with_retry(
                "/works",
                params={"search": title, "per_page": per_page},
            )
            data = response.json()

            results = data.get("results", [])
            works = [OpenAlexWork.from_api_response(item) for item in results]

            logger.info(
                "OpenAlex search for '%s' returned %d results",
                title[:50],
                len(works),
            )
            return works

        except httpx.HTTPError as e:
            logger.error("OpenAlex API error: %s", e)
            return []
        except Exception as e:
            logger.error("Error parsing OpenAlex response: %s", e)
            return []

    async def get_by_doi(self, doi: str) -> Optional[OpenAlexWork]:
        doi = _clean_doi(doi)

        doi_url = f"https://doi.org/{doi}"

        try:
            response = await self._get_with_retry(
                f"/works/{quote(doi_url, safe='')}",
                params={},
            )
            data = response.json()

            if data:
                work = OpenAlexWork.from_api_response(data)
                logger.info("OpenAlex DOI lookup for '%s' successful", doi)
                return work
            return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("DOI not found in OpenAlex: %s", doi)
            else:
                logger.error("OpenAlex API error: %s", e)
            return None
        except Exception as e:
            logger.error("Error parsing OpenAlex response: %s", e)
            return None

    async def find_best_match(
        self,
        title: str,
        authors: Optional[List[str]] = None,
        threshold: float = 0.8,
    ) -> Optional[OpenAlexWork]:
        works = await self.search_by_title(title, per_page=5)

        if not works:
            return None

        def _normalize(s: str) -> str:
            s = s.lower()
            s = re.sub(r"[^\w\s]", "", s)
            s = re.sub(r"\s+", " ", s).strip()
            return s

        def _similarity(s1: str, s2: str) -> float:
            words1 = set(_normalize(s1).split())
            words2 = set(_normalize(s2).split())
            if not words1 or not words2:
                return 0.0
            intersection = words1 & words2
            union = words1 | words2
            return len(intersection) / len(union)

        def _norm_author(a: str) -> str:
            a = a.lower()
            a = re.sub(r"[^\w\s]", " ", a)
            a = re.sub(r"\s+", " ", a).strip()
            return a

        def _author_overlap(a1: List[str], a2: List[str]) -> float:
            if not a1 or not a2:
                return 0.0
            s1 = {_norm_author(a) for a in a1 if a}
            s2 = {_norm_author(a) for a in a2 if a}
            if not s1 or not s2:
                return 0.0
            inter = s1 & s2
            union = s1 | s2
            return len(inter) / len(union) if union else 0.0

        query_authors = authors or []
        best_work = None
        best_score = 0.0

        for work in works:
            title_score = _similarity(title, work.title)
            author_score = _author_overlap(query_authors, work.authors)
            if query_authors:
                score = 0.75 * title_score + 0.25 * author_score
            else:
                score = title_score
            if score > best_score:
                best_score = score
                best_work = work

        if best_work and best_score >= threshold:
            logger.info(
                "Best OpenAlex match: '%s' (score: %.2f)",
                best_work.title[:50],
                best_score,
            )
            return best_work

        logger.warning(
            "No good OpenAlex match for '%s' (best score: %.2f)",
            title[:50],
            best_score,
        )
        return None

    async def enrich_paper(self, paper: PaperItem) -> PaperItem:
        work: Optional[OpenAlexWork] = None

        try:
            doi_candidate = paper.doi or _extract_doi_from_text(paper.url)
            if doi_candidate:
                work = await self.get_by_doi(doi_candidate)
            elif paper.title:
                work = await self.find_best_match(paper.title, authors=paper.authors)

            if work is None:
                logger.debug("No OpenAlex match for '%s'", paper.title[:60])
                extra = dict(paper.extra)
                extra["openalex_unmatched"] = {
                    "doi": paper.doi or _extract_doi_from_text(paper.url),
                    "title": paper.title,
                    "authors": paper.authors,
                    "url": paper.url,
                    "strategy": "doi_only" if doi_candidate else "title_author",
                }
                return paper.model_copy(update={"extra": extra})

            updates: Dict[str, Any] = {}

            if not paper.abstract and work.abstract:
                updates["abstract"] = work.abstract
            if not paper.authors and work.authors:
                updates["authors"] = work.authors
            if not paper.doi and work.doi:
                updates["doi"] = work.doi
            if not paper.url and work.url:
                updates["url"] = work.url
            if not paper.published_date and work.year:
                updates["published_date"] = date(work.year, 1, 1)
            if not paper.publication_title and work.journal:
                updates["publication_title"] = work.journal
            if not paper.volume and work.volume:
                updates["volume"] = work.volume
            if not paper.issue and work.issue:
                updates["issue"] = work.issue
            if not paper.pages and work.pages:
                updates["pages"] = work.pages
            if not paper.item_type or paper.item_type == "journalArticle":
                if work.item_type and work.item_type != "journalArticle":
                    updates["item_type"] = work.item_type

            extra = dict(paper.extra)
            extra["openalex"] = {
                "cited_by_count": work.cited_by_count,
                "concepts": work.concepts,
            }
            _mapped_keys = {
                "doi", "title", "display_name", "authorships",
                "primary_location", "publication_year", "biblio",
                "abstract_inverted_index", "type", "cited_by_count",
                "concepts", "id",
            }
            openalex_extra = {
                k: v for k, v in work.raw_data.items()
                if k not in _mapped_keys
            }
            if openalex_extra:
                extra["openalex_extra"] = openalex_extra
            updates["extra"] = extra

            enriched = paper.model_copy(update=updates)
            logger.info(
                "Enriched '%s' with OpenAlex data (updated %d fields)",
                paper.title[:50],
                len(updates) - 1,
            )
            return enriched

        except Exception as e:
            logger.error(
                "Error enriching paper '%s' from OpenAlex: %s",
                paper.title[:50],
                e,
            )
            return paper

