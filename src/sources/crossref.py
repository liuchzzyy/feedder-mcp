"""CrossRef API client for academic metadata lookup and enrichment."""

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from src.config.settings import get_crossref_config
from src.models.responses import PaperItem
from src.utils.text import DOI_PATTERN, clean_abstract

logger = logging.getLogger(__name__)

SELECT_FIELDS = (
    "DOI,title,author,container-title,published,"
    "published-print,published-online,"
    "volume,issue,page,abstract,URL,ISSN,"
    "publisher,type,subject,funder,reference,link"
)


def _clean_doi(doi: str) -> str:
    if doi.startswith("https://doi.org/"):
        return doi[16:]
    elif doi.startswith("http://doi.org/"):
        return doi[15:]
    elif doi.startswith("doi:"):
        return doi[4:]
    return doi.strip()


def _extract_doi_from_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = DOI_PATTERN.search(value)
    if match:
        return match.group(0)
    return None


@dataclass
class CrossrefWork:
    """Represents a work (article) from CrossRef API."""

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
        doi = data.get("DOI", "")

        titles = data.get("title", [])
        title = titles[0] if titles else ""

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

        container_titles = data.get("container-title", [])
        journal = container_titles[0] if container_titles else ""

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

        volume = data.get("volume")
        issue = data.get("issue")
        pages = data.get("page")
        abstract = clean_abstract(data.get("abstract"))
        url = data.get("URL") or (f"https://doi.org/{doi}" if doi else None)
        publisher = data.get("publisher")

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

        subjects = data.get("subject", [])

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

        references = data.get("reference", [])
        citation_count = len(references) if references else None

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
    """Async client for querying the CrossRef API."""

    def __init__(self, email: Optional[str] = None) -> None:
        config = get_crossref_config()
        if email is None:
            email = config.get("email")
        self.email = email
        self._api_base: str = config.get("api_base", "https://api.crossref.org")
        self._timeout: float = config.get("timeout", 45.0)
        self._user_agent: str = config.get(
            "user_agent",
            "feedder-mcp/2.0 (https://github.com/feedder-mcp; mailto:{email})",
        )
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def _headers(self) -> Dict[str, str]:
        ua = self._user_agent.format(email=self.email or "noreply@example.com")
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

    async def search_by_title(
        self,
        title: str,
        rows: int = 5,
    ) -> List[CrossrefWork]:
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
        client = await self._get_client()
        doi = _clean_doi(doi)

        try:
            response = await client.get(f"/works/{quote(doi, safe='')}")
            response.raise_for_status()
            data = response.json()

            work_data = data.get("message", {})
            if work_data:
                work = CrossrefWork.from_api_response(work_data)
                logger.info("CrossRef DOI lookup for '%s' successful", doi)
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
        work: Optional[CrossrefWork] = None

        try:
            doi_candidate = paper.doi or _extract_doi_from_text(paper.url)
            if doi_candidate:
                work = await self.get_by_doi(doi_candidate)

            if work is None and paper.title:
                work = await self.find_best_match(paper.title)

            if work is None and paper.url:
                work = await self.find_best_match(paper.url)

            if work is None:
                logger.debug("No CrossRef match for '%s'", paper.title[:60])
                extra = dict(paper.extra)
                extra["crossref_unmatched"] = {
                    "doi": paper.doi or _extract_doi_from_text(paper.url),
                    "title": paper.title,
                    "url": paper.url,
                }
                return paper.model_copy(update={"extra": extra})

            updates: Dict[str, Any] = {}

            if work.abstract:
                updates["abstract"] = work.abstract
            if work.authors:
                updates["authors"] = work.authors
            if work.doi:
                updates["doi"] = work.doi
            if work.url:
                updates["url"] = work.url
            if work.pdf_url:
                updates["pdf_url"] = work.pdf_url
            if work.year:
                updates["published_date"] = date(work.year, 1, 1)
            if work.journal:
                updates["publication_title"] = work.journal
            if work.publisher:
                updates["publisher"] = work.publisher
            if work.volume:
                updates["volume"] = work.volume
            if work.issue:
                updates["issue"] = work.issue
            if work.pages:
                updates["pages"] = work.pages
            if work.item_type:
                updates["item_type"] = work.item_type

            issn_list = work.raw_data.get("ISSN", [])
            if issn_list and isinstance(issn_list, list):
                updates["issn"] = issn_list[0]

            lang = work.raw_data.get("language")
            if lang:
                updates["language"] = lang

            extra = dict(paper.extra)
            extra["crossref"] = {
                "funders": work.funders,
                "citation_count": work.citation_count,
                "subjects": work.subjects,
            }
            _mapped_keys = {
                "DOI", "title", "author", "container-title",
                "published", "published-print", "published-online",
                "volume", "issue", "page", "abstract", "URL",
                "publisher", "type", "subject", "funder",
                "reference", "link", "ISSN", "language",
            }
            crossref_extra = {
                k: v for k, v in work.raw_data.items()
                if k not in _mapped_keys
            }
            if crossref_extra:
                extra["crossref_extra"] = crossref_extra
            updates["extra"] = extra

            enriched = paper.model_copy(update=updates)
            logger.info(
                "Enriched '%s' with CrossRef data (updated %d fields)",
                paper.title[:50],
                len(updates) - 1,
            )
            return enriched

        except Exception as e:
            logger.error(
                "Error enriching paper '%s' from CrossRef: %s",
                paper.title[:50],
                e,
            )
            return paper
