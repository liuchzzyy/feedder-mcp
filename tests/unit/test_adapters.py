"""Unit tests for export adapters."""

import json
import pytest
from datetime import date
from unittest.mock import AsyncMock

import src.adapters.zotero as zotero_module
from src.adapters.json import JSONAdapter
from src.adapters.zotero import ZoteroAdapter, zotero_available
from src.models.responses import PaperItem


@pytest.fixture
def sample_papers():
    """Create sample papers for testing."""
    return [
        PaperItem(
            title="Test Paper 1",
            authors=["Author One", "Author Two"],
            abstract="This is a test abstract",
            published_date=date(2024, 1, 15),
            doi="10.1234/test1",
            url="https://example.com/paper1",
            pdf_url="https://example.com/paper1.pdf",
            source="Test Source",
            source_id="test-001",
            source_type="rss",
            extra={"raw_data": "sample"},
        ),
        PaperItem(
            title="Test Paper 2",
            authors=["Author Three"],
            abstract="Another test abstract",
            published_date=date(2024, 2, 20),
            doi="10.1234/test2",
            source="Test Source",
            source_type="email",
        ),
    ]


class TestJSONAdapter:
    """Test cases for JSONAdapter."""

    @pytest.mark.asyncio
    async def test_json_adapter_export(self, sample_papers, tmp_path):
        """Test basic JSON export functionality."""
        adapter = JSONAdapter()
        filepath = tmp_path / "output.json"

        result = await adapter.export(
            papers=sample_papers,
            filepath=str(filepath),
            include_metadata=False,
        )

        # Verify result
        assert result["success"] is True
        assert result["count"] == 2
        assert filepath.exists()

        # Verify file contents
        with filepath.open("r") as f:
            data = json.load(f)

        assert len(data) == 2
        assert data[0]["title"] == "Test Paper 1"
        assert data[1]["title"] == "Test Paper 2"
        assert "extra" not in data[0]  # Should be excluded

    @pytest.mark.asyncio
    async def test_json_adapter_with_metadata(self, sample_papers, tmp_path):
        """Test JSON export with metadata included."""
        adapter = JSONAdapter()
        filepath = tmp_path / "output_with_metadata.json"

        result = await adapter.export(
            papers=sample_papers,
            filepath=str(filepath),
            include_metadata=True,
        )

        # Verify result
        assert result["success"] is True
        assert result["count"] == 2

        # Verify file contents
        with filepath.open("r") as f:
            data = json.load(f)

        assert len(data) == 2
        assert "extra" in data[0]
        assert data[0]["extra"]["raw_data"] == "sample"

    @pytest.mark.asyncio
    async def test_json_adapter_empty_list(self, tmp_path):
        """Test exporting empty paper list."""
        adapter = JSONAdapter()
        filepath = tmp_path / "empty.json"

        result = await adapter.export(
            papers=[],
            filepath=str(filepath),
        )

        # Verify result
        assert result["success"] is True
        assert result["count"] == 0

        # Verify file contents
        with filepath.open("r") as f:
            data = json.load(f)

        assert data == []

    @pytest.mark.asyncio
    async def test_json_adapter_creates_directories(self, tmp_path):
        """Test that export creates parent directories."""
        adapter = JSONAdapter()
        nested_path = tmp_path / "deep" / "nested" / "output.json"

        result = await adapter.export(
            papers=[
                PaperItem(
                    title="Test",
                    source="Test",
                    source_type="rss",
                )
            ],
            filepath=str(nested_path),
        )

        # Verify result and file creation
        assert result["success"] is True
        assert nested_path.exists()


class TestZoteroAdapter:
    """Test cases for ZoteroAdapter."""

    def test_zotero_adapter_import_error(self):
        """Test that ZoteroAdapter raises clear error when zotero-mcp not available."""
        if not zotero_available:
            with pytest.raises(ImportError) as exc_info:
                ZoteroAdapter(
                    library_id="test",
                    api_key="test",
                )

            assert "zotero-mcp" in str(exc_info.value)

    def test_paper_to_zotero_item_conversion(self):
        """Test conversion of PaperItem to Zotero format."""
        if not zotero_available:
            pytest.skip("zotero-mcp not available")

        paper = PaperItem(
            title="Test Paper",
            authors=["Author One", "Author Two"],
            abstract="Test abstract",
            published_date=date(2024, 1, 15),
            doi="10.1234/test",
            url="https://example.com",
            source="Test",
            source_type="rss",
        )

        adapter = ZoteroAdapter(
            library_id="test",
            api_key="test",
        )
        zotero_item = adapter._paper_to_zotero_item(paper)

        # Verify structure
        assert zotero_item["itemType"] == "journalArticle"
        assert zotero_item["title"] == "Test Paper"
        assert len(zotero_item["creators"]) == 2
        assert zotero_item["creators"][0]["creatorType"] == "author"
        assert zotero_item["creators"][0]["name"] == "Author One"
        assert zotero_item["abstractNote"] == "Test abstract"
        assert zotero_item["DOI"] == "10.1234/test"
        assert zotero_item["date"] == "2024-01-15"
        assert "accessDate" in zotero_item

    def test_paper_to_zotero_item_minimal(self):
        """Test conversion with minimal required fields."""
        if not zotero_available:
            pytest.skip("zotero-mcp not available")

        paper = PaperItem(
            title="Minimal Paper",
            source="Test",
            source_type="email",
        )

        adapter = ZoteroAdapter(
            library_id="test",
            api_key="test",
        )
        zotero_item = adapter._paper_to_zotero_item(paper)

        # Verify basic structure
        assert zotero_item["itemType"] == "journalArticle"
        assert zotero_item["title"] == "Minimal Paper"
        assert zotero_item["creators"] == []
        assert "accessDate" in zotero_item

    def test_paper_to_zotero_item_preprint_removes_journal_fields(self):
        """Preprint should not include journalArticle-only fields."""
        if not zotero_available:
            pytest.skip("zotero-mcp not available")

        paper = PaperItem(
            title="Preprint Paper",
            publication_title="SSRN",
            journal_abbreviation="J. Test",
            issn="1234-5678",
            volume="1",
            issue="2",
            pages="3-4",
            item_type="preprint",
            source="Test",
            source_type="rss",
        )

        adapter = ZoteroAdapter(
            library_id="test",
            api_key="test",
        )
        zotero_item = adapter._paper_to_zotero_item(paper)

        assert zotero_item["itemType"] == "preprint"
        assert zotero_item.get("repository") == "SSRN"
        assert "publicationTitle" not in zotero_item
        assert "journalAbbreviation" not in zotero_item
        assert "ISSN" not in zotero_item
        assert "volume" not in zotero_item
        assert "issue" not in zotero_item
        assert "pages" not in zotero_item
        assert "publisher" not in zotero_item

    @pytest.mark.asyncio
    async def test_zotero_adapter_init_requires_core(self):
        """Test that adapter initialization fails gracefully without zotero-mcp."""
        if not zotero_available:
            with pytest.raises(ImportError) as exc_info:
                ZoteroAdapter(
                    library_id="test",
                    api_key="test",
                )

            # Verify helpful error message
            error_msg = str(exc_info.value)
            assert "zotero-mcp" in error_msg

    @pytest.mark.asyncio
    async def test_zotero_adapter_export_requires_core(self):
        """Test that export fails gracefully without zotero-mcp."""
        if not zotero_available:
            # Can't even create adapter without zotero-mcp
            with pytest.raises(ImportError):
                adapter = ZoteroAdapter(
                    library_id="test",
                    api_key="test",
                )
                await adapter.export(
                    papers=[
                        PaperItem(
                            title="Test",
                            source="Test",
                            source_type="rss",
                        )
                    ],
                )

    @pytest.mark.asyncio
    async def test_zotero_export_skips_existing_by_doi(self, monkeypatch):
        """Export skips items that already exist in library by DOI."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._item_service.list_items = AsyncMock(
            return_value=[
                {
                    "data": {
                        "title": "Existing Paper",
                        "DOI": "10.1234/existing",
                        "date": "2024-01-01",
                        "creators": [{"name": "Author One"}],
                    }
                }
            ]
        )
        adapter._item_service.create_item = AsyncMock(
            return_value={"created": [{}], "skipped_duplicates": [], "failed": []}
        )
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="Existing Paper title variant",
                doi="https://doi.org/10.1234/EXISTING",
                source="Test",
                source_type="rss",
            ),
            PaperItem(
                title="Brand New Paper",
                doi="10.9999/new",
                source="Test",
                source_type="rss",
            ),
        ]

        result = await adapter.export(papers)

        assert result["success_count"] == 1
        assert result["skipped_count"] == 1
        assert result["skipped_by_key"]["doi"] == 1
        adapter._item_service.create_item.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_zotero_export_skips_existing_by_title_date(self, monkeypatch):
        """When DOI is missing, export falls back to title+date."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._item_service.get_items = AsyncMock(
            return_value=[
                {
                    "data": {
                        "title": "A New Framework for Batteries",
                        "date": "2025-03-08",
                    }
                }
            ]
        )
        adapter._item_service.create_item = AsyncMock(
            return_value={"created": [{}], "skipped_duplicates": [], "failed": []}
        )
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="A New Framework for Batteries",
                published_date=date(2025, 3, 8),
                source="Test",
                source_type="rss",
            ),
            PaperItem(
                title="Another Fresh Paper",
                published_date=date(2025, 3, 8),
                source="Test",
                source_type="rss",
            ),
        ]

        result = await adapter.export(papers)

        assert result["success_count"] == 1
        assert result["skipped_count"] == 1
        assert result["skipped_by_key"]["title_date"] == 1
        adapter._item_service.create_item.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_zotero_export_without_doi_falls_back_to_url(self, monkeypatch):
        """When DOI is missing and title+date does not match, URL should be used."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._item_service.get_items = AsyncMock(
            return_value=[
                {
                    "data": {
                        "title": "Old Title",
                        "date": "2025-03-01",
                        "url": "https://example.com/paper-abc?utm_source=mail",
                    }
                }
            ]
        )
        adapter._item_service.create_item = AsyncMock(
            return_value={"created": [{}], "skipped_duplicates": [], "failed": []}
        )
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="Completely Different Title",
                published_date=date(2025, 3, 8),
                url="https://example.com/paper-abc",
                source="Test",
                source_type="rss",
            )
        ]

        result = await adapter.export(papers)

        assert result["success_count"] == 0
        assert result["skipped_count"] == 1
        assert result["skipped_by_key"]["url"] == 1
        adapter._item_service.create_item.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_zotero_export_counts_runtime_skipped_duplicates(self, monkeypatch):
        """create_item summary with skipped_duplicates should update skipped_count."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._item_service.list_items = AsyncMock(return_value=[])
        adapter._item_service.create_item = AsyncMock(
            return_value={"created": [], "failed": [], "skipped_duplicates": [{}]}
        )
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="Duplicate In Runtime Check",
                doi="10.7777/dup",
                source="Test",
                source_type="rss",
            )
        ]

        result = await adapter.export(papers)

        assert result["success_count"] == 0
        assert result["skipped_count"] == 1
        assert result["skipped_by_key"]["doi"] == 1

    @pytest.mark.asyncio
    async def test_zotero_export_continues_when_preload_fails(self, monkeypatch):
        """Export should continue even if preloading existing items fails."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._load_existing_identity_keys = AsyncMock(
            side_effect=RuntimeError("preload failed")
        )
        adapter._item_service.create_item = AsyncMock(
            return_value={"created": [{"key": "X"}], "skipped_duplicates": [], "failed": []}
        )
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="Paper After Preload Failure",
                doi="10.5555/preload",
                source="Test",
                source_type="rss",
            )
        ]

        result = await adapter.export(papers)

        assert result["success_count"] == 1
        assert result["skipped_count"] == 0
        assert result["failures"] == []
        adapter._item_service.create_item.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_zotero_export_does_not_infer_success_for_unknown_result_shape(
        self, monkeypatch
    ):
        """Unknown create_item result shape should not be counted as success."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._item_service.list_items = AsyncMock(return_value=[])
        adapter._item_service.create_item = AsyncMock(return_value={"ok": True})
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="Unknown Result Shape Paper",
                doi="10.8888/unknown-shape",
                source="Test",
                source_type="rss",
            )
        ]

        result = await adapter.export(papers)

        assert result["success_count"] == 0
        assert result["skipped_count"] == 0
        assert result["failures"] == []

    @pytest.mark.asyncio
    async def test_zotero_list_existing_items_supports_start_pagination(
        self, monkeypatch
    ):
        """Preload should paginate when list_items supports start/limit."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        class _PagedService:
            def __init__(self):
                self.calls = []

            async def list_items(self, limit=100, start=0):
                self.calls.append({"limit": limit, "start": start})
                total = 251
                if start >= total:
                    return []
                end = min(start + limit, total)
                return [{"data": {"title": f"Paper {i}"}} for i in range(start, end)]

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = _PagedService()
        adapter._api_client = AsyncMock()
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        items = await adapter._list_existing_items()

        assert len(items) == 251
        assert adapter._item_service.calls == [
            {"limit": 100, "start": 0},
            {"limit": 100, "start": 100},
            {"limit": 100, "start": 200},
        ]

    @pytest.mark.asyncio
    async def test_zotero_export_resolves_collection_name_to_key(self, monkeypatch):
        """Collection name should be resolved to key before create_item."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._api_client.get_collections = AsyncMock(
            return_value=[{"key": "866TNWZ9", "data": {"name": "00_INBOXS_AA"}}]
        )
        adapter._item_service.list_items = AsyncMock(return_value=[])
        adapter._item_service.create_item = AsyncMock(
            return_value={"created": [{}], "failed": {}, "skipped_duplicates": 0}
        )
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="Collection Name Resolution",
                doi="10.7777/collection-name",
                source="Test",
                source_type="rss",
            )
        ]

        result = await adapter.export(papers, collection_id="00_INBOXS_AA")

        assert result["success_count"] == 1
        payload = adapter._item_service.create_item.await_args.args[0]
        assert payload.get("collections") == ["866TNWZ9"]

    @pytest.mark.asyncio
    async def test_zotero_export_surfaces_failed_detail_message(self, monkeypatch):
        """Failure message should include detail returned by create_item."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._item_service.list_items = AsyncMock(return_value=[])
        adapter._item_service.create_item = AsyncMock(
            return_value={
                "successful": {},
                "failed": {"0": {"code": 400, "message": "invalid collection key"}},
                "created": 0,
                "failed_count": 1,
                "skipped_duplicates": 0,
            }
        )
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="Failure Detail Test",
                doi="10.7777/failure-detail",
                source="Test",
                source_type="rss",
            )
        ]

        result = await adapter.export(papers, collection_id="BADNAME1")

        assert result["success_count"] == 0
        assert len(result["failures"]) == 1
        assert "invalid collection key" in result["failures"][0]["error"]

    @pytest.mark.asyncio
    async def test_zotero_export_counts_successful_map_shape(self, monkeypatch):
        """Result shape with 'successful' map should count as created."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._item_service.list_items = AsyncMock(return_value=[])
        adapter._item_service.create_item = AsyncMock(
            return_value={
                "successful": {"0": {"key": "ABCD1234"}},
                "created": 0,
                "failed": {},
                "skipped_duplicates": 0,
            }
        )
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="Successful Map Shape",
                doi="10.1111/successful-shape",
                source="Test",
                source_type="rss",
            )
        ]

        result = await adapter.export(papers, collection_id="ABCD1234")

        assert result["success_count"] == 1
        assert result["skipped_count"] == 0

    @pytest.mark.asyncio
    async def test_zotero_export_collection_name_requires_resolution(self, monkeypatch):
        """Collection names should fail if client cannot resolve names to keys."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = object()  # no get_collections method
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        with pytest.raises(ValueError):
            await adapter._resolve_collection_key("00_INBOXS_AA")

    def test_normalize_item_list_result_supports_model_dump_items(self):
        """Adapter should normalize SearchResult-like objects from newer zotero-mcp."""

        class _FakeSearchResult:
            def model_dump(self):
                return {
                    "title": "A New Framework for Batteries",
                    "doi": "10.1234/test-doi",
                    "year": 2025,
                    "authors": "Wang",
                }

        normalized = ZoteroAdapter._normalize_item_list_result([_FakeSearchResult()])
        assert isinstance(normalized, list)
        assert len(normalized) == 1
        data = normalized[0]["data"]
        assert data["DOI"] == "10.1234/test-doi"
        assert data["title"] == "A New Framework for Batteries"
        assert data["date"] == "2025"
        assert data["creators"][0]["name"] == "Wang"

    @pytest.mark.asyncio
    async def test_zotero_export_skips_existing_from_get_all_items_models(
        self, monkeypatch
    ):
        """Export pre-check should work when get_all_items returns model-like results."""
        monkeypatch.setattr(zotero_module, "zotero_available", True)

        class _FakeSearchResult:
            def model_dump(self):
                return {
                    "title": "Existing Paper",
                    "doi": "10.1234/existing",
                    "year": 2024,
                    "authors": "Author One",
                }

        adapter = ZoteroAdapter.__new__(ZoteroAdapter)
        adapter._item_service = AsyncMock()
        adapter._api_client = AsyncMock()
        adapter._item_service.list_items = None
        adapter._item_service.get_items = None
        adapter._item_service.get_all_items = AsyncMock(
            return_value=[_FakeSearchResult()]
        )
        adapter._item_service.create_item = AsyncMock()
        adapter._logger = zotero_module.logging.getLogger("test.zotero")

        papers = [
            PaperItem(
                title="Existing Paper with Variant Title",
                doi="https://doi.org/10.1234/EXISTING",
                source="Test",
                source_type="rss",
            )
        ]

        result = await adapter.export(papers)

        assert result["success_count"] == 0
        assert result["skipped_count"] == 1
        assert result["skipped_by_key"]["doi"] == 1
        adapter._item_service.create_item.assert_not_awaited()
