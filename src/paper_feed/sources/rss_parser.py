"""RSS feed parser for converting feed entries to PaperItem objects."""

import logging
import re
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from paper_feed.core.models import PaperItem

logger = logging.getLogger(__name__)

# DOI pattern for extraction
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)


class RSSParser:
    """Parser for RSS feed entries to PaperItem objects.

    Handles extraction of authors, dates, DOIs, and PDF URLs from
    various RSS feed formats (arXiv, bioRxiv, Nature, Science, etc.).
    """

    def parse(
        self,
        entry: Dict[str, Any],
        source_name: str,
        feed_meta: Optional[Dict[str, Any]] = None,
    ) -> PaperItem:
        """Parse an RSS feed entry into a PaperItem.

        Args:
            entry: Feedparser entry object (dict-like).
            source_name: Name of the RSS source (e.g., "arXiv", "Nature").
            feed_meta: Optional feed-level metadata dict (title, language,
                version, subtitle, encoding) passed from RSSSource.

        Returns:
            PaperItem with extracted metadata.

        Raises:
            ValueError: If required fields (title) are missing.
        """
        # Extract required fields
        title = self._get_field(entry, "title")
        if not title:
            raise ValueError("Entry missing required field: title")

        # Extract optional fields
        authors = self._extract_authors(entry)
        published_date = self._extract_published_date(entry)
        doi = self._extract_doi(entry)
        pdf_url = self._extract_pdf_url(entry)

        # Extract abstract — prefer entry.content (Atom rich content),
        # fall back to summary, then description
        abstract = self._extract_abstract(entry)

        url = self._get_field(entry, "link") or ""
        source_id = self._get_field(entry, "id") or url

        # Build rich metadata from feedparser fields
        metadata = self._extract_metadata(entry, feed_meta)

        return PaperItem(
            title=str(title),
            authors=authors,
            abstract=str(abstract) if abstract else "",
            published_date=published_date,
            doi=doi,
            url=url if url else None,
            pdf_url=pdf_url,
            source=source_name,
            source_id=source_id if source_id else None,
            source_type="rss",
            metadata=metadata,
        )

    def _get_field(self, entry: Any, key: str, default: Any = None) -> Any:
        """Safely get value from entry (dict or object).

        Args:
            entry: Feedparser entry (may be dict or object)
            key: Field name to retrieve
            default: Default value if field not found

        Returns:
            Field value or default
        """
        if isinstance(entry, dict):
            return entry.get(key, default)
        return getattr(entry, key, default)

    def _extract_abstract(self, entry: Any) -> str:
        """Extract abstract from entry, preferring rich content.

        Checks in order:
        1. ``entry.content`` — Atom feeds provide a list of content dicts
           with ``{type, value, base, language}``; use the first item's value.
        2. ``entry.summary`` — RSS ``<description>`` / Atom ``<summary>``.
        3. ``entry.description`` — legacy fallback.

        Args:
            entry: Feedparser entry.

        Returns:
            Abstract string, or empty string if nothing found.
        """
        # Prefer entry.content (Atom rich content)
        content_field = self._get_field(entry, "content")
        if content_field and isinstance(content_field, list):
            for content_item in content_field:
                value = None
                if isinstance(content_item, dict):
                    value = content_item.get("value")
                elif hasattr(content_item, "value"):
                    value = content_item.value
                if value and isinstance(value, str) and value.strip():
                    return value

        # Fall back to summary / description
        return (
            self._get_field(entry, "summary")
            or self._get_field(entry, "description")
            or ""
        )

    def _extract_authors(self, entry: Any) -> List[str]:
        """Extract authors from entry, including contributors.

        Handles multiple formats:
        - entry.authors (list of objects with .name or .email)
        - entry.author (string)
        - entry.contributors (additional contributor list, appended)

        Args:
            entry: Feedparser entry.

        Returns:
            List of author names.
        """
        authors = []

        # Try entry.authors (list format)
        authors_field = self._get_field(entry, "authors")
        if authors_field:
            if isinstance(authors_field, list):
                for author_obj in authors_field:
                    if hasattr(author_obj, "name"):
                        authors.append(str(author_obj.name))
                    elif hasattr(author_obj, "email"):
                        authors.append(str(author_obj.email))
                    elif isinstance(author_obj, dict):
                        name = author_obj.get("name")
                        if name:
                            authors.append(str(name))

        # Fallback to entry.author (string format)
        if not authors:
            author_field = self._get_field(entry, "author")
            if author_field:
                # Handle common formats: "Name", "Name1, Name2", etc.
                author_str = str(author_field)
                # Split by common separators
                for sep in [",", ";", " and "]:
                    if sep in author_str:
                        authors = [a.strip() for a in author_str.split(sep)]
                        break
                else:
                    authors = [author_str]

        # Append contributors (Atom feeds)
        contributors = self._get_field(entry, "contributors")
        if contributors and isinstance(contributors, list):
            existing = {a.lower() for a in authors}
            for contrib in contributors:
                name = None
                if isinstance(contrib, dict):
                    name = contrib.get("name")
                elif hasattr(contrib, "name"):
                    name = contrib.name
                if name and str(name).lower() not in existing:
                    authors.append(str(name))
                    existing.add(str(name).lower())

        return authors

    def _extract_published_date(self, entry: Any) -> Optional[date]:
        """Extract publication date from entry.

        Handles time.struct_time from feedparser.

        Args:
            entry: Feedparser entry

        Returns:
            Publication date as date object or None
        """
        # Try published_parsed first
        published_parsed = self._get_field(entry, "published_parsed")
        if published_parsed and isinstance(published_parsed, time.struct_time):
            try:
                dt = datetime.fromtimestamp(time.mktime(published_parsed))
                return dt.date()
            except (ValueError, OSError):
                pass

        # Try updated_parsed as fallback
        updated_parsed = self._get_field(entry, "updated_parsed")
        if updated_parsed and isinstance(updated_parsed, time.struct_time):
            try:
                dt = datetime.fromtimestamp(time.mktime(updated_parsed))
                return dt.date()
            except (ValueError, OSError):
                pass

        return None

    def _extract_doi(self, entry: Any) -> str:
        """Extract DOI from entry metadata or links.

        Checks:
        1. dc_identifier field
        2. prism_doi field
        3. Links/guid containing doi.org URLs

        Args:
            entry: Feedparser entry

        Returns:
            DOI string, or empty string if not found.
        """
        # Try common DOI fields
        for key in ["dc_identifier", "prism_doi"]:
            val = self._get_field(entry, key)
            if val and isinstance(val, str):
                # Clean up doi: prefix
                if val.lower().startswith("doi:"):
                    val = val[4:].strip()
                if DOI_PATTERN.match(val):
                    return val

        # Try to find DOI in links
        for key in ["link", "id"]:
            val = self._get_field(entry, key)
            if val and isinstance(val, str):
                match = DOI_PATTERN.search(val)
                if match:
                    return match.group(0)

        return ""

    def _extract_pdf_url(self, entry: Any) -> Optional[str]:
        """Extract direct PDF URL from entry.

        Handles:
        1. Links with type="application/pdf"
        2. Enclosures with type="application/pdf" (RSS media attachments)
        3. arXiv /abs/ URLs → convert to /pdf/
        4. pdf_url field (some publishers)

        Args:
            entry: Feedparser entry.

        Returns:
            Direct PDF URL or None.
        """
        # Check for links with PDF type
        links = self._get_field(entry, "links")
        if links and isinstance(links, list):
            for link in links:
                if isinstance(link, dict):
                    link_type = link.get("type", "")
                    href = link.get("href", "")
                    if link_type == "application/pdf" and href:
                        return str(href)
                elif hasattr(link, "type") and link.type == "application/pdf":
                    if hasattr(link, "href"):
                        return str(link.href)

        # Check enclosures (RSS media attachments — e.g. <enclosure> tag)
        enclosures = self._get_field(entry, "enclosures")
        if enclosures and isinstance(enclosures, list):
            for enc in enclosures:
                enc_type = ""
                enc_href = ""
                if isinstance(enc, dict):
                    enc_type = enc.get("type", "")
                    enc_href = enc.get("href", "")
                elif hasattr(enc, "type") and hasattr(enc, "href"):
                    enc_type = getattr(enc, "type", "")
                    enc_href = getattr(enc, "href", "")
                if enc_type == "application/pdf" and enc_href:
                    return str(enc_href)

        # Check for pdf_url field
        pdf_url_field = self._get_field(entry, "pdf_url")
        if pdf_url_field:
            return str(pdf_url_field)

        # Convert arXiv /abs/ URLs to /pdf/
        link = self._get_field(entry, "link")
        if link and isinstance(link, str):
            if "arxiv.org/abs/" in link:
                return link.replace("/abs/", "/pdf/") + ".pdf"

        return None

    def _extract_metadata(
        self,
        entry: Any,
        feed_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build rich metadata dict from feedparser entry and feed-level info.

        Extracts publisher, rights/license, content type details, and
        feed-level metadata (title, language, version) when available.
        All data is stored in ``PaperItem.metadata`` without changing
        the PaperItem schema.

        Args:
            entry: Feedparser entry.
            feed_meta: Optional feed-level metadata from RSSSource.

        Returns:
            Metadata dict with available fields.
        """
        meta: Dict[str, Any] = {}

        # Publisher info
        publisher = self._get_field(entry, "publisher")
        if publisher:
            meta["publisher"] = str(publisher)
        else:
            publisher_detail = self._get_field(entry, "publisher_detail")
            if publisher_detail:
                name = None
                if isinstance(publisher_detail, dict):
                    name = publisher_detail.get("name")
                elif hasattr(publisher_detail, "name"):
                    name = publisher_detail.name
                if name:
                    meta["publisher"] = str(name)

        # Rights / license
        rights = self._get_field(entry, "rights")
        if rights:
            meta["rights"] = str(rights)

        # Content type awareness from *_detail fields
        summary_detail = self._get_field(entry, "summary_detail")
        if summary_detail:
            detail: Dict[str, Any] = {}
            if isinstance(summary_detail, dict):
                for key in ("type", "language", "base"):
                    val = summary_detail.get(key)
                    if val:
                        detail[key] = str(val)
            elif hasattr(summary_detail, "type"):
                for key in ("type", "language", "base"):
                    val = getattr(summary_detail, key, None)
                    if val:
                        detail[key] = str(val)
            if detail:
                meta["summary_detail"] = detail

        # Source info for aggregated feeds (entry.source)
        source_info = self._get_field(entry, "source")
        if source_info:
            src: Dict[str, Any] = {}
            if isinstance(source_info, dict):
                for key in ("title", "href", "url"):
                    val = source_info.get(key)
                    if val:
                        src[key] = str(val)
            elif hasattr(source_info, "title"):
                for key in ("title", "href", "url"):
                    val = getattr(source_info, key, None)
                    if val:
                        src[key] = str(val)
            if src:
                meta["original_source"] = src

        # Feed-level metadata (passed from RSSSource)
        if feed_meta:
            feed_info: Dict[str, Any] = {}
            for key in ("title", "language", "version", "subtitle", "encoding"):
                val = feed_meta.get(key)
                if val:
                    feed_info[key] = str(val)
            if feed_info:
                meta["feed"] = feed_info

        return meta
