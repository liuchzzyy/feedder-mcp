"""Zotero export adapter for feedder-mcp."""

from __future__ import annotations

import inspect
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.models.responses import ExportAdapter, PaperItem
from src.utils.dedup import paper_export_identity_keys, zotero_data_identity_keys

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
        skipped_by_key = {"doi": 0, "title_date": 0, "url": 0}
        resolved_collection_id = await self._resolve_collection_key(collection_id)
        collection_keys = [resolved_collection_id] if resolved_collection_id else None
        try:
            existing_key_set = await self._load_existing_identity_keys()
        except Exception as exc:
            self._logger.warning(
                "Failed to preload Zotero items for deduplication; "
                "continuing export without pre-check: %s",
                exc,
            )
            existing_key_set = set()

        for paper in papers:
            try:
                identity_keys = paper_export_identity_keys(paper)
                matched_key: Optional[tuple[str, str]] = None
                for identity_key in identity_keys:
                    if identity_key in existing_key_set:
                        matched_key = identity_key
                        break

                if matched_key:
                    skipped_count += 1
                    skipped_by_key[matched_key[0]] = skipped_by_key.get(
                        matched_key[0], 0
                    ) + 1
                    continue

                zotero_item = self._paper_to_zotero_item(
                    paper, collection_keys=collection_keys
                )
                create_result = await self._item_service.create_item(zotero_item)
                created_n, skipped_n, failed_n = self._extract_create_result_counts(
                    create_result
                )

                success_count += created_n
                skipped_count += skipped_n
                if skipped_n > 0 and identity_keys:
                    key_kind = identity_keys[0][0]
                    skipped_by_key[key_kind] = skipped_by_key.get(
                        key_kind, 0
                    ) + skipped_n

                if created_n > 0:
                    for k in zotero_data_identity_keys(zotero_item):
                        existing_key_set.add(k)

                if failed_n > 0:
                    failures.append(
                        {
                            "title": paper.title,
                            "error": self._summarize_create_failures(
                                create_result, failed_n
                            ),
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

    async def _resolve_collection_key(
        self, collection_id: Optional[str]
    ) -> Optional[str]:
        if not collection_id:
            return None

        value = str(collection_id).strip()
        if not value:
            return None

        if self._looks_like_collection_key(value):
            return value

        get_collections = getattr(self._api_client, "get_collections", None)
        if not callable(get_collections):
            self._logger.warning(
                "Collection identifier '%s' does not look like a key; "
                "collection name resolution is unavailable.",
                value,
            )
            return value

        try:
            raw_collections = await self._invoke_method(get_collections)
        except Exception as exc:
            self._logger.warning(
                "Failed to resolve collection name '%s'; using as-is: %s",
                value,
                exc,
            )
            return value

        if not isinstance(raw_collections, list):
            return value

        exact_match_key = None
        casefold_match_key = None
        for item in raw_collections:
            if not isinstance(item, dict):
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else item
            name = data.get("name")
            key = item.get("key") or data.get("key")
            if not isinstance(name, str) or not isinstance(key, str):
                continue
            if name == value:
                exact_match_key = key
                break
            if casefold_match_key is None and name.casefold() == value.casefold():
                casefold_match_key = key

        resolved_key = exact_match_key or casefold_match_key
        if resolved_key:
            self._logger.info(
                "Resolved collection '%s' -> key '%s'",
                value,
                resolved_key,
            )
            return resolved_key

        self._logger.warning(
            "Collection '%s' was not found by name; using as-is.",
            value,
        )
        return value

    @staticmethod
    def _looks_like_collection_key(value: str) -> bool:
        return re.fullmatch(r"[A-Za-z0-9]{8}", value) is not None

    def _paper_to_zotero_item(
        self, paper: PaperItem, collection_keys: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        item_type = paper.item_type or "journalArticle"
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
            "itemType": item_type,
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

        zotero_item = self._normalize_item_for_type(zotero_item, item_type)
        zotero_item = {k: v for k, v in zotero_item.items() if v is not None}

        return zotero_item

    @staticmethod
    def _normalize_item_for_type(
        zotero_item: Dict[str, Any], item_type: str
    ) -> Dict[str, Any]:
        normalized_type = (item_type or "").strip().lower()
        if normalized_type != "preprint":
            return zotero_item

        publication_title = zotero_item.get("publicationTitle")
        if publication_title and not zotero_item.get("repository"):
            zotero_item["repository"] = publication_title

        # Keep a conservative field subset for preprint to avoid invalid-field failures.
        allowed_fields = {
            "itemType",
            "title",
            "creators",
            "abstractNote",
            "repository",
            "archive",
            "archiveLocation",
            "DOI",
            "citationKey",
            "url",
            "accessDate",
            "date",
            "shortTitle",
            "language",
            "rights",
            "collections",
            "extra",
        }
        return {k: v for k, v in zotero_item.items() if k in allowed_fields}

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
                    items = await self._collect_items(method)
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

    async def _collect_items(self, method: Any) -> Optional[List[Dict[str, Any]]]:
        page_size = 1000
        page_cursor_key = None
        if self._method_accepts_param(method, "start"):
            page_cursor_key = "start"
        elif self._method_accepts_param(method, "offset"):
            page_cursor_key = "offset"

        if not page_cursor_key:
            result = await self._invoke_method(method, limit=100000)
            return self._normalize_item_list_result(result)

        all_items: List[Dict[str, Any]] = []
        cursor = 0
        max_pages = 200
        for _ in range(max_pages):
            kwargs: Dict[str, Any] = {"limit": page_size, page_cursor_key: cursor}
            result = await self._invoke_method(method, **kwargs)
            batch = self._normalize_item_list_result(result)
            if batch is None:
                return None
            all_items.extend(batch)
            if len(batch) < page_size:
                break
            cursor += len(batch)
        else:
            self._logger.warning(
                "Zotero item preload reached max pages (%d); list may be truncated.",
                max_pages,
            )

        return all_items

    @staticmethod
    def _method_accepts_param(method: Any, param_name: str) -> bool:
        signature = inspect.signature(method)
        return param_name in signature.parameters

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
        def _normalize_list(values: List[Any]) -> List[Dict[str, Any]]:
            normalized: List[Dict[str, Any]] = []
            for value in values:
                item = ZoteroAdapter._coerce_item_to_dict(value)
                if item is not None:
                    normalized.append(item)
            return normalized

        if isinstance(result, list):
            return _normalize_list(result)
        if isinstance(result, dict):
            for key in ("items", "results", "data"):
                value = result.get(key)
                if isinstance(value, list):
                    return _normalize_list(value)
                if isinstance(value, dict):
                    nested_items = value.get("items")
                    if isinstance(nested_items, list):
                        return _normalize_list(nested_items)
            normalized = ZoteroAdapter._coerce_item_to_dict(result)
            if normalized is not None:
                return [normalized]
        return None

    @staticmethod
    def _coerce_item_to_dict(item: Any) -> Optional[Dict[str, Any]]:
        if isinstance(item, dict):
            return ZoteroAdapter._coerce_flat_item_dict(item)

        dumped: Any = None
        model_dump = getattr(item, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump()
        else:
            dict_method = getattr(item, "dict", None)
            if callable(dict_method):
                dumped = dict_method()

        if isinstance(dumped, dict):
            return ZoteroAdapter._coerce_flat_item_dict(dumped)

        attrs: Dict[str, Any] = {}
        for key in (
            "raw_data",
            "DOI",
            "doi",
            "title",
            "date",
            "year",
            "creators",
            "authors",
            "url",
        ):
            value = getattr(item, key, None)
            if value is not None:
                attrs[key] = value

        if attrs:
            return ZoteroAdapter._coerce_flat_item_dict(attrs)
        return None

    @staticmethod
    def _coerce_flat_item_dict(item: Dict[str, Any]) -> Dict[str, Any]:
        data = item.get("data")
        if isinstance(data, dict):
            return item

        raw_data = item.get("raw_data")
        mapped: Dict[str, Any] = {}

        if isinstance(raw_data, dict):
            nested = raw_data.get("data")
            if isinstance(nested, dict):
                return raw_data
            mapped.update(raw_data)

        title = item.get("title")
        if title and "title" not in mapped:
            mapped["title"] = title

        doi = item.get("DOI") or item.get("doi")
        if doi and "DOI" not in mapped:
            mapped["DOI"] = doi

        date_value = item.get("date")
        if not date_value:
            year = item.get("year")
            if year is not None and str(year).strip():
                date_value = str(year)
        if date_value and "date" not in mapped:
            mapped["date"] = str(date_value)

        creators_value = item.get("creators")
        if not creators_value:
            creators_value = item.get("authors")
        creators = ZoteroAdapter._coerce_creators(creators_value)
        if creators and "creators" not in mapped:
            mapped["creators"] = creators

        url = item.get("url")
        if url and "url" not in mapped:
            mapped["url"] = url

        if mapped:
            return {"data": mapped}
        return item

    @staticmethod
    def _coerce_creators(value: Any) -> List[Dict[str, Any]]:
        if isinstance(value, list):
            creators: List[Dict[str, Any]] = []
            for entry in value:
                if isinstance(entry, dict):
                    name = (
                        entry.get("name")
                        or entry.get("lastName")
                        or entry.get("firstName")
                    )
                    if name:
                        creators.append(entry)
                elif isinstance(entry, str):
                    name = entry.strip()
                    if name:
                        creators.append({"creatorType": "author", "name": name})
            return creators

        if isinstance(value, str):
            authors: List[Dict[str, Any]] = []
            normalized = value.replace(" and ", ";")
            for chunk in normalized.split(";"):
                name = chunk.strip()
                if name:
                    authors.append({"creatorType": "author", "name": name})
            return authors

        return []

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

    @staticmethod
    def _summarize_create_failures(result: Any, failed_n: int) -> str:
        if isinstance(result, dict):
            failed = result.get("failed")
            if isinstance(failed, dict) and failed:
                messages: List[str] = []
                for detail in failed.values():
                    if isinstance(detail, dict):
                        msg = detail.get("message") or detail.get("error")
                        if msg:
                            messages.append(str(msg))
                        else:
                            messages.append(str(detail))
                    else:
                        messages.append(str(detail))
                if messages:
                    deduped = list(dict.fromkeys(messages))
                    return "; ".join(deduped)

            failures = result.get("failures")
            if isinstance(failures, list) and failures:
                messages = []
                for detail in failures:
                    if isinstance(detail, dict):
                        msg = detail.get("message") or detail.get("error")
                        if msg:
                            messages.append(str(msg))
                    elif detail:
                        messages.append(str(detail))
                if messages:
                    deduped = list(dict.fromkeys(messages))
                    return "; ".join(deduped)

        return f"create_item reported {failed_n} failed item(s)"

