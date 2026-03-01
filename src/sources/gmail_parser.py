"""Gmail HTML email parser for extracting paper items."""

import logging
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from src.models.responses import PaperItem
from src.utils.dedup import deduplicate_papers, normalize_title
from src.utils.text import DOI_PATTERN, clean_title

logger = logging.getLogger(__name__)


class GmailParser:
    """Parser for extracting paper items from HTML email content."""

    @staticmethod
    def _item_quality(item: PaperItem) -> int:
        score = 0
        if item.doi:
            score += 4
        if item.url:
            score += 2
        if item.abstract:
            score += 1
        score += min(len(item.authors), 3)
        return score

    def _deduplicate_by_title(
        self,
        items: List[PaperItem],
    ) -> Tuple[List[PaperItem], int]:
        title_to_index: dict[str, int] = {}
        unique: List[PaperItem] = []
        dropped = 0

        for item in items:
            title_key = normalize_title(item.title)
            if not title_key:
                unique.append(item)
                continue

            existing_index = title_to_index.get(title_key)
            if existing_index is None:
                title_to_index[title_key] = len(unique)
                unique.append(item)
                continue

            dropped += 1
            existing_item = unique[existing_index]
            if self._item_quality(item) > self._item_quality(existing_item):
                unique[existing_index] = item

        return unique, dropped

    def parse(
        self,
        html_content: str,
        source_name: str,
        email_id: str = "",
        email_subject: str = "",
    ) -> List[PaperItem]:
        if not html_content:
            return []

        soup = BeautifulSoup(html_content, "html.parser")
        items: List[PaperItem] = []

        # Strategy 1: Look for table rows with links
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                item = self._extract_item_from_row(
                    row, source_name, email_id, email_subject
                )
                if item:
                    items.append(item)

        # Strategy 2: Look for article-like divs/sections
        items.extend(
            self._extract_items_from_divs(
                soup, source_name, email_id, email_subject
            )
        )

        # Strategy 3: Extract from plain links with surrounding text
        items.extend(
            self._extract_items_from_links(
                soup, source_name, email_id, email_subject
            )
        )

        identity_unique_items, dedup_stats = deduplicate_papers(items)
        unique_items, title_dropped = self._deduplicate_by_title(identity_unique_items)

        logger.info(
            (
                "Extracted %d items from email %s "
                "(raw=%d, dropped_identity=%d, dropped_title=%d, by_key=%s)"
            ),
            len(unique_items),
            email_id[:8] + "..." if email_id else "(no id)",
            dedup_stats["input_count"],
            dedup_stats["dropped_count"],
            title_dropped,
            dedup_stats["duplicates_by_key"],
        )
        return unique_items

    def _extract_item_from_row(
        self,
        row: Tag,
        source_name: str,
        email_id: str,
        email_subject: str,
    ) -> Optional[PaperItem]:
        title = ""
        link = ""

        links = row.find_all("a", href=True)
        for a in links:
            href_value = a.get("href", "")
            href = href_value if isinstance(href_value, str) else ""
            text = a.get_text(strip=True)

            if len(text) < 10 or text.lower() in (
                "read more",
                "view",
                "click here",
            ):
                continue

            if not title or len(text) > len(title):
                title = text
                link = href

        if not title:
            cells = row.find_all(["td", "th"])
            for cell in cells:
                text = cell.get_text(strip=True)
                if 20 < len(text) < 500:
                    title = text
                    break

        if not title or len(title) < 10:
            return None

        doi = None
        row_text = row.get_text()
        doi_match = DOI_PATTERN.search(link) or DOI_PATTERN.search(row_text)
        if doi_match:
            doi = doi_match.group(0)

        authors: List[str] = []
        journal = None
        cells = row.find_all(["td", "th"])
        for cell in cells:
            text = cell.get_text(strip=True)
            if text == title:
                continue
            if "," in text and len(text) < 200:
                if not authors:
                    authors = [a.strip() for a in text.split(",")]
            elif len(text) < 100 and not journal:
                journal = text

        return PaperItem(
            title=clean_title(title),
            authors=authors,
            abstract="",
            published_date=None,
            doi=doi or "",
            url=link if link else None,
            pdf_url=None,
            source=source_name,
            source_id=email_id or None,
            source_type="email",
            extra={
                "email_id": email_id,
                "email_subject": email_subject,
            },
        )

    def _extract_items_from_divs(
        self,
        soup: BeautifulSoup,
        source_name: str,
        email_id: str,
        email_subject: str,
    ) -> List[PaperItem]:
        items: List[PaperItem] = []

        for container in soup.find_all(["div", "article", "section"]):
            link_elem = container.find("a", href=True)
            if not link_elem:
                continue

            title = link_elem.get_text(strip=True)
            link_value = link_elem.get("href", "")
            link = link_value if isinstance(link_value, str) else ""

            if len(title) < 15:
                heading = container.find(["h1", "h2", "h3", "h4"])
                if heading:
                    title = heading.get_text(strip=True)

            if len(title) < 15 or len(title) > 500:
                continue

            doi = None
            container_text = container.get_text()
            doi_match = DOI_PATTERN.search(link) or DOI_PATTERN.search(container_text)
            if doi_match:
                doi = doi_match.group(0)

            items.append(
                PaperItem(
                    title=clean_title(title),
                    authors=[],
                    abstract="",
                    published_date=None,
                    doi=doi or "",
                    url=link if link else None,
                    pdf_url=None,
                    source=source_name,
                    source_id=email_id or None,
                    source_type="email",
                    extra={
                        "email_id": email_id,
                        "email_subject": email_subject,
                    },
                )
            )

        return items

    def _extract_items_from_links(
        self,
        soup: BeautifulSoup,
        source_name: str,
        email_id: str,
        email_subject: str,
    ) -> List[PaperItem]:
        items: List[PaperItem] = []

        _PUBLISHER_DOMAINS = [
            "doi.org",
            "nature.com",
            "science.org",
            "wiley.com",
            "springer.com",
            "acs.org",
            "rsc.org",
            "elsevier.com",
            "cell.com",
            "pnas.org",
            "sciencedirect.com",
            "arxiv.org",
            "biorxiv.org",
            "medrxiv.org",
        ]

        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href_value = a.get("href", "")
            href = href_value if isinstance(href_value, str) else ""

            if len(text) < 20 or len(text) > 500:
                continue
            if text.lower() in ("unsubscribe", "view in browser", "read more"):
                continue

            is_article_link = any(
                domain in href.lower() for domain in _PUBLISHER_DOMAINS
            )

            doi = None
            doi_match = DOI_PATTERN.search(href)
            if doi_match:
                doi = doi_match.group(0)
                is_article_link = True

            if is_article_link:
                items.append(
                    PaperItem(
                        title=clean_title(text),
                        authors=[],
                        abstract="",
                        published_date=None,
                        doi=doi or "",
                        url=href if href else None,
                        pdf_url=None,
                        source=source_name,
                        source_id=email_id or None,
                        source_type="email",
                        extra={
                            "email_id": email_id,
                            "email_subject": email_subject,
                        },
                    )
                )

        return items
