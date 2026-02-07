"""OpenAlex API client for academic metadata lookup and enrichment.

Queries the OpenAlex REST API to search by title or DOI, and enrich
PaperItem objects with metadata (abstract, authors, concepts, etc.).

API Docs: https://docs.openalex.org/
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from paper_feed.core.config import get_openalex_config
from paper_feed.core.models import PaperItem
from paper_feed.utils.text import clean_abstract

logger = logging.getLogger(__name__)


def _clean_doi(doi: str) -> str:
    """Strip common DOI URL prefixes.

    Args:
        doi: Raw DOI string.

    Returns:
        Cleaned DOI without URL prefix.
    """
    if doi.startswith("https://doi.org/"):
        return doi[16:]
    elif doi.startswith("http://doi.org/"):
        return doi[15:]
    elif doi.startswith("doi:"):
        return doi[4:]
    return doi.strip()


def _reconstruct_abstract(
    inverted_index: Optional[Dict[str, List[int]]],
) -> Optional[str]:
    """Reconstruct abstract text from OpenAlex inverted index.

    OpenAlex stores abstracts as {word: [positions]} dicts.
    This reconstructs the original text by sorting positions.

    Args:
        inverted_index: Word-to-positions mapping.

    Returns:
        Reconstructed abstract text, or None on failure.
    """
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


@dataclass
class OpenAlexWork:
    """Represents a work (article) from OpenAlex API.

    Attributes:
        doi: Digital Object Identifier (without URL prefix).
        title: Work title.
        authors: List of author display names.
        journal: Journal / source display name.
        year: Publication year.
        volume: Journal volume.
        issue: Journal issue.
        pages: Page range string.
        abstract: Reconstructed and cleaned abstract text.
        url: URL for the work.
        item_type: Mapped item type string.
        cited_by_count: Number of citations.
        concepts: Relevant concept names (score > 0.3).
        raw_data: Full API response dict.
    """

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
        """Parse an OpenAlex API response into an OpenAlexWork.

        Args:
            data: Single work dict from OpenAlex API.

        Returns:
            Populated OpenAlexWork instance.
        """
        # DOI — stored as URL, extract bare DOI
        doi_url = data.get("doi", "") or ""
        doi = doi_url.split("doi.org/")[-1] if "doi.org/" in doi_url else ""

        # Title
        title = data.get("title", "") or data.get("display_name", "") or ""

        # Authors from authorships
        authors: List[str] = []
        for authorship in data.get("authorships", []):
            author_data = authorship.get("author", {})
            name = author_data.get("display_name", "")
            if name:
                authors.append(name)

        # Journal from primary_location
        journal = None
        primary_location = data.get("primary_location") or {}
        if primary_location:
            source = primary_location.get("source") or {}
            if source:
                journal = source.get("display_name")

        # Year
        year = data.get("publication_year")

        # Volume, issue, pages from biblio
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

        # Abstract from inverted index
        abstract = _reconstruct_abstract(data.get("abstract_inverted_index"))

        # URL
        url = data.get("doi") or data.get("id")

        # Type mapping
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

        # Cited-by count
        cited_by_count = data.get("cited_by_count")
        if cited_by_count == 0:
            cited_by_count = None

        # Concepts filtered by relevance score > 0.3
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
    """Async client for querying the OpenAlex API.

    Supports searching by title, looking up by DOI, finding best
    matches, and enriching PaperItem objects with metadata.

    Args:
        email: Email for polite pool access.
            Loaded from config if not provided.
    """

    def __init__(self, email: Optional[str] = None) -> None:
        """Initialize the OpenAlex client.

        Args:
            email: Optional email for polite pool access.
        """
        config = get_openalex_config()
        if email is None:
            email = config.get("email")
        self.email = email
        self._api_base: str = config.get("api_base", "https://api.openalex.org")
        self._timeout: float = config.get("timeout", 45.0)
        self._user_agent: str = config.get(
            "user_agent",
            "paper-feed/1.0 (https://github.com/paper-feed; mailto:{email})",
        )
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def _headers(self) -> Dict[str, str]:
        """Build request headers with polite pool info."""
        ua = self._user_agent.format(email=self.email or "noreply@example.com")
        headers = {"User-Agent": ua}
        if self.email:
            headers["mailto"] = self.email
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        Returns:
            Configured httpx.AsyncClient instance.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._api_base,
                headers=self._headers,
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def search_by_title(
        self,
        title: str,
        per_page: int = 5,
    ) -> List[OpenAlexWork]:
        """Search for works by title.

        Args:
            title: Title text to search for.
            per_page: Maximum number of results (default 5).

        Returns:
            List of OpenAlexWork objects.
        """
        client = await self._get_client()

        try:
            response = await client.get(
                "/works",
                params={
                    "search": title,
                    "per_page": per_page,
                },
            )
            response.raise_for_status()
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
        """Get work metadata by DOI.

        Args:
            doi: DOI string (with or without URL prefix).

        Returns:
            OpenAlexWork or None if not found.
        """
        client = await self._get_client()
        doi = _clean_doi(doi)

        # OpenAlex expects DOI in full URL format
        doi_url = f"https://doi.org/{doi}"

        try:
            response = await client.get(f"/works/{quote(doi_url, safe='')}")
            response.raise_for_status()
            data = response.json()

            if data:
                work = OpenAlexWork.from_api_response(data)
                logger.info(
                    "OpenAlex DOI lookup for '%s' successful",
                    doi,
                )
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
        threshold: float = 0.8,
    ) -> Optional[OpenAlexWork]:
        """Find the best matching work for a title.

        Uses Jaccard word similarity to score results.

        Args:
            title: Title to search for.
            threshold: Minimum similarity score (0-1).

        Returns:
            Best matching OpenAlexWork or None.
        """
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

        best_work = None
        best_score = 0.0

        for work in works:
            score = _similarity(title, work.title)
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
        """Enrich a PaperItem with OpenAlex metadata.

        Tries DOI lookup first, then title search. Fills only
        missing fields; does not overwrite existing data.

        Args:
            paper: PaperItem to enrich.

        Returns:
            Enriched PaperItem (new instance via model_copy).
        """
        work: Optional[OpenAlexWork] = None

        try:
            # Strategy 1: DOI lookup (most reliable)
            if paper.doi:
                work = await self.get_by_doi(paper.doi)

            # Strategy 2: Title search
            if work is None and paper.title:
                work = await self.find_best_match(paper.title)

            if work is None:
                logger.debug(
                    "No OpenAlex match for '%s'",
                    paper.title[:60],
                )
                return paper

            # Build update dict — only fill missing fields
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

            # Store OpenAlex metadata
            metadata = dict(paper.metadata)
            metadata["openalex"] = {
                "journal": work.journal,
                "cited_by_count": work.cited_by_count,
                "concepts": work.concepts,
                "volume": work.volume,
                "issue": work.issue,
                "pages": work.pages,
                "item_type": work.item_type,
            }
            updates["metadata"] = metadata

            enriched = paper.model_copy(update=updates)
            logger.info(
                "Enriched '%s' with OpenAlex data (updated %d fields)",
                paper.title[:50],
                len(updates) - 1,  # exclude metadata
            )
            return enriched

        except Exception as e:
            logger.error(
                "Error enriching paper '%s' from OpenAlex: %s",
                paper.title[:50],
                e,
            )
            return paper
