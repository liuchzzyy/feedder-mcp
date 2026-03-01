"""Unit tests for enrichment service behaviors."""

from unittest.mock import AsyncMock, patch

import pytest

from src.services.enrich import EnrichService
from src.sources.openalex import OpenAlexWork


class TestEnrichServiceValidation:
    @pytest.mark.asyncio
    async def test_enrich_rejects_invalid_provider(self):
        service = EnrichService()
        with pytest.raises(ValueError):
            await service.enrich([], provider="invalid", concurrency=1)

    @pytest.mark.asyncio
    async def test_enrich_rejects_invalid_concurrency(self):
        service = EnrichService()
        with pytest.raises(ValueError):
            await service.enrich([], provider="all", concurrency=0)


class TestEnrichServiceOpenAlex:
    @pytest.mark.asyncio
    async def test_search_openalex_uses_per_page(self):
        service = EnrichService()

        with patch("src.services.enrich.OpenAlexClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.search_by_title = AsyncMock(return_value=[])
            mock_client_cls.return_value = mock_client

            await service.search_openalex("test")

            mock_client.search_by_title.assert_awaited_once_with("test", per_page=5)

    def test_openalex_work_to_dict_uses_existing_fields(self):
        work = OpenAlexWork(
            doi="10.1000/test",
            title="Test Paper",
            authors=["A One"],
            journal="Nature",
            year=2024,
            volume="1",
            issue="2",
            pages="10-20",
            abstract="text",
            url="https://doi.org/10.1000/test",
            item_type="journalArticle",
            cited_by_count=5,
            concepts=["AI"],
            raw_data={
                "id": "https://openalex.org/W123",
                "primary_location": {
                    "pdf_url": "https://example.com/file.pdf",
                    "source": {"host_organization_name": "Nature Publishing Group"},
                },
            },
        )

        result = EnrichService.openalex_work_to_dict(work)

        assert result["id"] == "https://openalex.org/W123"
        assert result["publisher"] == "Nature Publishing Group"
        assert result["pdf_url"] == "https://example.com/file.pdf"
