"""CrossRef API client for academic metadata lookup and enrichment.

Queries the CrossRef REST API to search by title or DOI, and enrich
PaperItem objects with metadata (abstract, authors, DOI, etc.).

API Docs: https://api.crossref.org/swagger-ui/index.html
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from paper_feed.core.config import get_crossref_config
from paper_feed.core.models import PaperItem
from paper_feed.utils.text import clean_abstract

logger = logging.getLogger(__name__)

# Fields to select from CrossRef API (reduces response size)
SELECT_FIELDS = (
    "DOI,title,author,container-title,published,"
    "published-print,published-online,"
    "volume,issue,page,abstract,URL,ISSN,"
    "publisher,type,subject,funder,reference,link"
)


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


@dataclass
class CrossrefWork:
    """Represents a work (article) from CrossRef API.

    Attributes:
        doi: Digital Object Identifier.
        title: Work title.
        authors: List of author names in "Family, Given" format.
        journal: Journal / container title.
        year: Publication year.
        volume: Journal volume.
        issue: Journal issue.
        pages: Page range string.
        abstract: Cleaned abstract text.
        url: URL for the work.
        publisher: Publisher name.
        item_type: Mapped item type string.
        subjects: Subject keywords from CrossRef.
        funders: Funder strings with optional award numbers.
        citation_count: Number of references (proxy for citations).
        pdf_url: Direct PDF link if available.
        raw_data: Full API response dict.
    """

    doi: str = ""
    title: str = ""
    authors: List[str] = field(default_factory=list)
    journal: str = ""
    year: Optional[int] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    abstract: Optional[str] = None
    url: Optional[str] = None
    publisher: Optional[str] = None
    item_type: str = "journalArticle"
    subjects: List[str] = field(default_factory=list)
    funders: List[str] = field(default_factory=list)
    citation_count: Optional[int] = None
    pdf_url: Optional[str] = None
    raw_data: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "CrossrefWork":
        """Parse a CrossRef API response into a CrossrefWork.

        Args:
            data: Single work dict from CrossRef API.

        Returns:
            Populated CrossrefWork instance.
        """
        # DOI
        doi = data.get("DOI", "")

        # Title (list of titles, take first)
        titles = data.get("title", [])
        title = titles[0] if titles else ""

        # Authors — "Family, Given" format
        authors: List[str] = []
        for author in data.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            if given and family:
                authors.append(f"{family}, {given}")
            elif family:
                authors.append(family)
            elif author.get("name"):
                authors.append(author["name"])

        # Journal / container title
        container_titles = data.get("container-title", [])
        journal = container_titles[0] if container_titles else ""

        # Year from published date
        year = None
        published = (
            data.get("published")
            or data.get("published-print")
            or data.get("published-online")
        )
        if published and "date-parts" in published:
            date_parts = published["date-parts"]
            if date_parts and date_parts[0]:
                year = date_parts[0][0]

        # Volume, issue, pages
        volume = data.get("volume")
        issue = data.get("issue")
        pages = data.get("page")

        # Abstract — clean HTML/XML
        abstract = clean_abstract(data.get("abstract"))

        # URL
        url = data.get("URL") or (f"https://doi.org/{doi}" if doi else None)

        # Publisher
        publisher = data.get("publisher")

        # Type mapping
        crossref_type = data.get("type", "")
        type_mapping = {
            "journal-article": "journalArticle",
            "proceedings-article": "conferencePaper",
            "book-chapter": "bookSection",
            "book": "book",
            "report": "report",
            "dataset": "dataset",
            "dissertation": "thesis",
            "posted-content": "preprint",
        }
        item_type = type_mapping.get(crossref_type, "journalArticle")

        # Subjects
        subjects = data.get("subject", [])

        # Funders with award numbers
        funders: List[str] = []
        for funder in data.get("funder", []):
            if isinstance(funder, dict):
                funder_name = funder.get("name")
                if funder_name:
                    funder_str = funder_name
                    awards = funder.get("award", [])
                    if awards:
                        award_str = ", ".join(str(a) for a in awards[:3])
                        funder_str += f" (Awards: {award_str})"
                    funders.append(funder_str)

        # Citation count (from references list length)
        references = data.get("reference", [])
        citation_count = len(references) if references else None

        # PDF URL from links
        pdf_url = None
        for link in data.get("link", []):
            if isinstance(link, dict) and link.get("content-type") == "application/pdf":
                pdf_url = link.get("URL")
                break

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
            publisher=publisher,
            item_type=item_type,
            subjects=subjects,
            funders=funders,
            citation_count=citation_count,
            pdf_url=pdf_url,
            raw_data=data,
        )


class CrossrefClient:
    """Async client for querying the CrossRef API.

    Supports searching by title, looking up by DOI, finding best
    matches, and enriching PaperItem objects with metadata.

    Args:
        email: Email for polite pool access (faster rate limits).
            Loaded from config if not provided.
    """

    def __init__(self, email: Optional[str] = None) -> None:
        """Initialize the CrossRef client.

        Args:
            email: Optional email for polite pool access.
        """
        config = get_crossref_config()
        if email is None:
            email = config.get("email")
        self.email = email
        self._api_base: str = config.get("api_base", "https://api.crossref.org")
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
        rows: int = 5,
    ) -> List[CrossrefWork]:
        """Search for works by title.

        Args:
            title: Title text to search for.
            rows: Maximum number of results (default 5).

        Returns:
            List of CrossrefWork objects.
        """
        client = await self._get_client()

        try:
            response = await client.get(
                "/works",
                params={
                    "query.title": title,
                    "rows": rows,
                    "select": SELECT_FIELDS,
                },
            )
            response.raise_for_status()
            data = response.json()

            items = data.get("message", {}).get("items", [])
            works = [CrossrefWork.from_api_response(item) for item in items]

            logger.info(
                "CrossRef search for '%s' returned %d results",
                title[:50],
                len(works),
            )
            return works

        except httpx.HTTPError as e:
            logger.error("CrossRef API error: %s", e)
            return []
        except Exception as e:
            logger.error("Error parsing CrossRef response: %s", e)
            return []

    async def get_by_doi(self, doi: str) -> Optional[CrossrefWork]:
        """Get work metadata by DOI.

        Args:
            doi: DOI string (with or without URL prefix).

        Returns:
            CrossrefWork or None if not found.
        """
        client = await self._get_client()
        doi = _clean_doi(doi)

        try:
            response = await client.get(f"/works/{quote(doi, safe='')}")
            response.raise_for_status()
            data = response.json()

            work_data = data.get("message", {})
            if work_data:
                work = CrossrefWork.from_api_response(work_data)
                logger.info(
                    "CrossRef DOI lookup for '%s' successful",
                    doi,
                )
                return work
            return None

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("DOI not found in CrossRef: %s", doi)
            else:
                logger.error("CrossRef API error: %s", e)
            return None
        except Exception as e:
            logger.error("Error parsing CrossRef response: %s", e)
            return None

    async def find_best_match(
        self,
        title: str,
        threshold: float = 0.8,
    ) -> Optional[CrossrefWork]:
        """Find the best matching work for a title.

        Uses Jaccard word similarity to score results.

        Args:
            title: Title to search for.
            threshold: Minimum similarity score (0-1).

        Returns:
            Best matching CrossrefWork or None.
        """
        works = await self.search_by_title(title, rows=5)

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
                "Best CrossRef match: '%s' (score: %.2f)",
                best_work.title[:50],
                best_score,
            )
            return best_work

        logger.warning(
            "No good CrossRef match for '%s' (best score: %.2f)",
            title[:50],
            best_score,
        )
        return None

    async def enrich_paper(self, paper: PaperItem) -> PaperItem:
        """Enrich a PaperItem with CrossRef metadata.

        Tries DOI lookup first, then title search. Fills only
        missing fields; does not overwrite existing data.

        Args:
            paper: PaperItem to enrich.

        Returns:
            Enriched PaperItem (new instance via model_copy).
        """
        work: Optional[CrossrefWork] = None

        try:
            # Strategy 1: DOI lookup (most reliable)
            if paper.doi:
                work = await self.get_by_doi(paper.doi)

            # Strategy 2: Title search
            if work is None and paper.title:
                work = await self.find_best_match(paper.title)

            if work is None:
                logger.debug(
                    "No CrossRef match for '%s'",
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

            if not paper.pdf_url and work.pdf_url:
                updates["pdf_url"] = work.pdf_url

            if not paper.published_date and work.year:
                updates["published_date"] = date(work.year, 1, 1)

            # Store CrossRef metadata
            metadata = dict(paper.metadata)
            metadata["crossref"] = {
                "journal": work.journal,
                "publisher": work.publisher,
                "volume": work.volume,
                "issue": work.issue,
                "pages": work.pages,
                "funders": work.funders,
                "citation_count": work.citation_count,
                "subjects": work.subjects,
                "item_type": work.item_type,
            }
            updates["metadata"] = metadata

            enriched = paper.model_copy(update=updates)
            logger.info(
                "Enriched '%s' with CrossRef data (updated %d fields)",
                paper.title[:50],
                len(updates) - 1,  # exclude metadata
            )
            return enriched

        except Exception as e:
            logger.error(
                "Error enriching paper '%s' from CrossRef: %s",
                paper.title[:50],
                e,
            )
            return paper
