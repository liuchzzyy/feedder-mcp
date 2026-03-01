"""RSS feed parser for converting feed entries to PaperItem objects."""

import logging
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

from src.models.responses import PaperItem

logger = logging.getLogger(__name__)

# DOI pattern for extraction
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)


class RSSParser:
    """Parser for RSS feed entries to PaperItem objects."""

    def parse(
        self,
        entry: Dict[str, Any],
        source_name: str,
        feed_meta: Optional[Dict[str, Any]] = None,
    ) -> PaperItem:
        title = self._get_field(entry, "title")
        if not title:
            raise ValueError("Entry missing required field: title")

        authors = self._extract_authors(entry)
        published_date = self._extract_published_date(entry)
        doi = self._extract_doi(entry)
        pdf_url = self._extract_pdf_url(entry)
        abstract = self._extract_abstract(entry)

        url = self._get_field(entry, "link") or ""
        source_id = self._get_field(entry, "id") or url

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
            extra=metadata,
        )

    def _get_field(self, entry: Any, key: str, default: Any = None) -> Any:
        if isinstance(entry, dict):
            return entry.get(key, default)
        return getattr(entry, key, default)

    def _extract_abstract(self, entry: Any) -> str:
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

        return (
            self._get_field(entry, "summary")
            or self._get_field(entry, "description")
            or ""
        )

    def _extract_authors(self, entry: Any) -> List[str]:
        authors = []

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

        if not authors:
            author_field = self._get_field(entry, "author")
            if author_field:
                author_str = str(author_field)
                for sep in [",", ";", " and "]:
                    if sep in author_str:
                        authors = [a.strip() for a in author_str.split(sep)]
                        break
                else:
                    authors = [author_str]

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
        published_parsed = self._get_field(entry, "published_parsed")
        if published_parsed and isinstance(published_parsed, time.struct_time):
            try:
                return date(
                    published_parsed.tm_year,
                    published_parsed.tm_mon,
                    published_parsed.tm_mday,
                )
            except ValueError:
                pass

        updated_parsed = self._get_field(entry, "updated_parsed")
        if updated_parsed and isinstance(updated_parsed, time.struct_time):
            try:
                return date(
                    updated_parsed.tm_year,
                    updated_parsed.tm_mon,
                    updated_parsed.tm_mday,
                )
            except ValueError:
                pass

        return None

    def _extract_doi(self, entry: Any) -> str:
        for key in ["dc_identifier", "prism_doi"]:
            val = self._get_field(entry, key)
            if val and isinstance(val, str):
                if val.lower().startswith("doi:"):
                    val = val[4:].strip()
                if DOI_PATTERN.match(val):
                    return val

        for key in ["link", "id"]:
            val = self._get_field(entry, key)
            if val and isinstance(val, str):
                match = DOI_PATTERN.search(val)
                if match:
                    return match.group(0)

        return ""

    def _extract_pdf_url(self, entry: Any) -> Optional[str]:
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

        pdf_url_field = self._get_field(entry, "pdf_url")
        if pdf_url_field:
            return str(pdf_url_field)

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
        meta: Dict[str, Any] = {}

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

        rights = self._get_field(entry, "rights")
        if rights:
            meta["rights"] = str(rights)

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

        if feed_meta:
            feed_info: Dict[str, Any] = {}
            for key in ("title", "language", "version", "subtitle", "encoding"):
                val = feed_meta.get(key)
                if val:
                    feed_info[key] = str(val)
            if feed_info:
                meta["feed"] = feed_info

        return meta
