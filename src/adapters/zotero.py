"""Zotero export adapter for feedder-mcp."""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.models.responses import ExportAdapter, PaperItem
from src.utils.dedup import paper_export_identity_key, zotero_data_identity_keys

try:
    from zotero_mcp.clients.zotero.api_client import ZoteroAPIClient
    from zotero_mcp.services.zotero.item_service import ItemService

    zotero_available = True
    _zotero_import_error: Exception | None = None
except Exception as exc:
    zotero_available = False
    _zotero_import_error = exc
    ZoteroAPIClient = None  # type: ignore[assignment,misc]
    ItemService = None  # type: ignore[assignment,misc]


class ZoteroAdapter(ExportAdapter):
    """Export papers to Zotero library via zotero-mcp."""

    adapter_name: str = "zotero"
    _ITEM_LIST_METHOD_CANDIDATES = (
        "list_items",
        "get_items",
        "get_all_items",
        "list",
    )

    def __init__(
        self,
        library_id: str,
        api_key: str,
        library_type: str = "user",
    ):
        if not zotero_available or ZoteroAPIClient is None or ItemService is None:
            raise ImportError(
                "zotero-mcp is required for ZoteroAdapter. "
                "Install it with: uv pip install /path/to/zotero-mcp"
            ) from _zotero_import_error

        self.library_id = library_id
        self.api_key = api_key
        self.library_type = library_type

        self._api_client = ZoteroAPIClient(
            library_id=library_id,
            library_type=library_type,
            api_key=api_key,
        )
        self._item_service = ItemService(api_client=self._api_client)
        self._logger = logging.getLogger(__name__)

    async def export(
        self,
        papers: List[PaperItem],
        collection_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if not zotero_available:
            raise ImportError(
                "zotero-mcp is required for ZoteroAdapter. "
                "Install it with: uv pip install /path/to/zotero-mcp"
            ) from _zotero_import_error

        success_count = 0
        failures = []
        skipped_count = 0
        skipped_by_key = {"doi": 0, "title_year_author": 0}
        collection_keys = [collection_id] if collection_id else None
        existing_key_set = await self._load_existing_identity_keys()

        for paper in papers:
            try:
                identity_key = paper_export_identity_key(paper)
                if identity_key and identity_key in existing_key_set:
                    skipped_count += 1
                    skipped_by_key[identity_key[0]] = skipped_by_key.get(
                        identity_key[0], 0
                    ) + 1
                    continue

                zotero_item = self._paper_to_zotero_item(
                    paper, collection_keys=collection_keys
                )
                create_result = await self._item_service.create_item(zotero_item)
                created_n, skipped_n, failed_n = self._extract_create_result_counts(
                    create_result
                )

                # Backward compatibility for APIs that return no structured summary.
                if created_n == 0 and skipped_n == 0 and failed_n == 0:
                    created_n = 1

                success_count += created_n
                skipped_count += skipped_n
                if skipped_n > 0 and identity_key:
                    skipped_by_key[identity_key[0]] = skipped_by_key.get(
                        identity_key[0], 0
                    ) + skipped_n

                if created_n > 0:
                    for k in zotero_data_identity_keys(zotero_item):
                        existing_key_set.add(k)

                if failed_n > 0:
                    failures.append(
                        {
                            "title": paper.title,
                            "error": f"create_item reported {failed_n} failed item(s)",
                        }
                    )
            except Exception as e:
                failures.append({"title": paper.title, "error": str(e)})

        self._logger.info(
            "Zotero export dedup stats: total=%d, exported=%d, skipped=%d, by_key=%s",
            len(papers),
            success_count,
            skipped_count,
            skipped_by_key,
        )

        return {
            "success_count": success_count,
            "total": len(papers),
            "skipped_count": skipped_count,
            "skipped_by_key": skipped_by_key,
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

    async def _load_existing_identity_keys(self) -> set[tuple[str, str]]:
        items = await self._list_existing_items()
        keys: set[tuple[str, str]] = set()
        for item in items:
            if isinstance(item, dict):
                keys.update(zotero_data_identity_keys(item))
        self._logger.info(
            "Loaded %d identity keys from %d existing Zotero items",
            len(keys),
            len(items),
        )
        return keys

    async def _list_existing_items(self) -> List[Dict[str, Any]]:
        for target in (self._item_service, self._api_client):
            for method_name in self._ITEM_LIST_METHOD_CANDIDATES:
                method = getattr(target, method_name, None)
                if not callable(method):
                    continue
                try:
                    result = await self._invoke_method(method, limit=100000)
                    items = self._normalize_item_list_result(result)
                    if items is not None:
                        return items
                except TypeError:
                    # Signature mismatch; keep trying other known method names.
                    continue
                except Exception as exc:
                    self._logger.warning(
                        "Failed to list Zotero items via %s.%s: %s",
                        target.__class__.__name__,
                        method_name,
                        exc,
                    )
                    continue

        raise RuntimeError(
            "Unable to list existing Zotero items for deduplication. "
            "No compatible list/get method found on zotero-mcp client."
        )

    @staticmethod
    async def _invoke_method(method: Any, **kwargs: Any) -> Any:
        signature = inspect.signature(method)
        supports_var_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in signature.parameters.values()
        )

        call_kwargs: Dict[str, Any] = {}
        for key, value in kwargs.items():
            if supports_var_kwargs or key in signature.parameters:
                call_kwargs[key] = value

        result = method(**call_kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _normalize_item_list_result(result: Any) -> Optional[List[Dict[str, Any]]]:
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            for key in ("items", "results", "data"):
                value = result.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
                if isinstance(value, dict):
                    nested_items = value.get("items")
                    if isinstance(nested_items, list):
                        return [item for item in nested_items if isinstance(item, dict)]
        return None

    @staticmethod
    def _extract_create_result_counts(result: Any) -> tuple[int, int, int]:
        """Parse create_item summary from different zotero-mcp return shapes."""
        if not isinstance(result, dict):
            return 0, 0, 0

        created = result.get("created")
        skipped = result.get("skipped_duplicates")
        failed = result.get("failed")
        failures = result.get("failures")

        def _count(value: Any) -> int:
            if isinstance(value, int):
                return max(0, value)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, dict):
                return len(value)
            return 0

        created_n = _count(created)
        skipped_n = _count(skipped)
        failed_n = _count(failed)
        if failed_n == 0:
            failed_n = _count(failures)

        if created_n == 0 and skipped_n == 0 and failed_n == 0:
            for key in ("created_count", "success_count", "inserted_count"):
                value = result.get(key)
                if isinstance(value, int) and value > 0:
                    created_n = value
                    break
            for key in ("skipped_count", "duplicate_count"):
                value = result.get(key)
                if isinstance(value, int) and value > 0:
                    skipped_n = value
                    break
            for key in ("failed_count", "error_count"):
                value = result.get(key)
                if isinstance(value, int) and value > 0:
                    failed_n = value
                    break

        return created_n, skipped_n, failed_n

