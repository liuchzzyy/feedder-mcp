"""Zotero export adapter for feedder-mcp."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

from src.models.responses import ExportAdapter, PaperItem

_ZOTERO_MCP_DEFAULT_PATH = Path(r"E:\Desktop\SciPapers\zotero-mcp\src")


def _ensure_zotero_mcp_on_path() -> bool:
    env_path = os.getenv("ZOTERO_MCP_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(_ZOTERO_MCP_DEFAULT_PATH)

    for candidate in candidates:
        if candidate.exists():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            return True
    return False


try:
    from zotero_mcp.config import Config
    from zotero_mcp.integration.zotero_integration import ZoteroIntegration

    zotero_available = True
    _zotero_import_error: Exception | None = None
except Exception as exc:
    if _ensure_zotero_mcp_on_path():
        try:
            from zotero_mcp.config import Config
            from zotero_mcp.integration.zotero_integration import ZoteroIntegration

            zotero_available = True
            _zotero_import_error = None
        except Exception as exc2:
            zotero_available = False
            _zotero_import_error = exc2
            Config = None
            ZoteroIntegration = None
    else:
        zotero_available = False
        _zotero_import_error = exc
        Config = None
        ZoteroIntegration = None


class ZoteroAdapter(ExportAdapter):
    """Export papers to Zotero library via zotero-mcp."""

    adapter_name: str = "zotero"

    def __init__(
        self,
        library_id: str,
        api_key: str,
        library_type: str = "user",
    ):
        if not zotero_available or Config is None or ZoteroIntegration is None:
            path_hint = str(_ZOTERO_MCP_DEFAULT_PATH)
            env_hint = "Set ZOTERO_MCP_PATH to the zotero-mcp src directory."
            raise ImportError(
                "zotero-mcp is required for ZoteroAdapter. "
                f"Expected repo at: {path_hint}. {env_hint}"
            ) from _zotero_import_error

        self.library_id = library_id
        self.api_key = api_key
        self.library_type = library_type

        self._config = Config(
            zotero_library_id=library_id,
            zotero_api_key=api_key,
            zotero_library_type=library_type,
        )
        self._integration = ZoteroIntegration(self._config)
        self._item_service = self._integration.item_service

    async def export(
        self,
        papers: List[PaperItem],
        collection_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if not zotero_available:
            raise ImportError(
                "zotero-mcp is required for ZoteroAdapter. "
                "Set ZOTERO_MCP_PATH or place the repo at the default path."
            ) from _zotero_import_error

        success_count = 0
        failures = []
        collection_keys = [collection_id] if collection_id else None

        for paper in papers:
            try:
                zotero_item = self._paper_to_zotero_item(
                    paper, collection_keys=collection_keys
                )
                await self._item_service.create_item(zotero_item)
                success_count += 1
            except Exception as e:
                failures.append({"title": paper.title, "error": str(e)})

        return {
            "success_count": success_count,
            "total": len(papers),
            "failures": failures,
        }

    def _paper_to_zotero_item(
        self, paper: PaperItem, collection_keys: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        creators = [
            {"creatorType": "author", "name": author} for author in paper.authors
        ]

        date_str = None
        if paper.published_date:
            date_str = paper.published_date.isoformat()

        access_date_str = None
        if paper.access_date:
            access_date_str = paper.access_date.isoformat()
        else:
            access_date_str = datetime.now().strftime("%Y-%m-%d")

        zotero_item: Dict[str, Any] = {
            "itemType": paper.item_type or "journalArticle",
            "title": paper.title,
            "creators": creators,
            "abstractNote": paper.abstract or None,
            "publicationTitle": paper.publication_title,
            "journalAbbreviation": paper.journal_abbreviation,
            "publisher": paper.publisher,
            "place": paper.place,
            "volume": paper.volume,
            "issue": paper.issue,
            "pages": paper.pages,
            "section": paper.section,
            "partNumber": paper.part_number,
            "partTitle": paper.part_title,
            "series": paper.series,
            "seriesTitle": paper.series_title,
            "seriesText": paper.series_text,
            "DOI": paper.doi,
            "citationKey": paper.citation_key,
            "url": paper.url,
            "accessDate": access_date_str,
            "PMID": paper.pmid,
            "PMCID": paper.pmcid,
            "ISSN": paper.issn,
            "archive": paper.archive,
            "archiveLocation": paper.archive_location,
            "shortTitle": paper.short_title,
            "language": paper.language,
            "libraryCatalog": paper.library_catalog,
            "callNumber": paper.call_number,
            "rights": paper.rights,
            "date": date_str,
        }

        if collection_keys:
            zotero_item["collections"] = collection_keys

        zotero_item = {k: v for k, v in zotero_item.items() if v is not None}

        return zotero_item
