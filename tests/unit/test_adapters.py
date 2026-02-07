"""Unit tests for export adapters."""

import json
import pytest
from datetime import date

from paper_feed.adapters.json import JSONAdapter
from paper_feed.adapters.zotero import ZoteroAdapter, zotero_available
from paper_feed.core.models import PaperItem


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
            metadata={"raw_data": "sample"},
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
        assert "metadata" not in data[0]  # Should be excluded

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
        assert "metadata" in data[0]
        assert data[0]["metadata"]["raw_data"] == "sample"

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
        """Test that ZoteroAdapter raises clear error when zotero-core not installed."""
        if not zotero_available:
            with pytest.raises(ImportError) as exc_info:
                ZoteroAdapter(
                    library_id="test",
                    api_key="test",
                )

            assert "zotero-core" in str(exc_info.value)

    def test_paper_to_zotero_item_conversion(self):
        """Test conversion of PaperItem to Zotero format."""
        if not zotero_available:
            pytest.skip("zotero-core not installed")

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
        assert len(zotero_item["tags"]) == 2
        assert zotero_item["tags"][0]["tag"] == "tag1"
        assert "accessDate" in zotero_item

    def test_paper_to_zotero_item_minimal(self):
        """Test conversion with minimal required fields."""
        if not zotero_available:
            pytest.skip("zotero-core not installed")

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
        assert zotero_item["abstractNote"] == ""
        assert "accessDate" in zotero_item

    @pytest.mark.asyncio
    async def test_zotero_adapter_init_requires_core(self):
        """Test that adapter initialization fails gracefully without zotero-core."""
        if not zotero_available:
            with pytest.raises(ImportError) as exc_info:
                ZoteroAdapter(
                    library_id="test",
                    api_key="test",
                )

            # Verify helpful error message
            error_msg = str(exc_info.value)
            assert "zotero-core" in error_msg
            assert "pip install" in error_msg

    @pytest.mark.asyncio
    async def test_zotero_adapter_export_requires_core(self):
        """Test that export fails gracefully without zotero-core."""
        if not zotero_available:
            # Can't even create adapter without zotero-core
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
