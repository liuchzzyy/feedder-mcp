"""Unit tests for CrossRef API client."""

import pytest
from datetime import date
from unittest.mock import patch, AsyncMock, MagicMock
from typing import Any, Dict

from paper_feed.sources.crossref import (
    _clean_doi,
    CrossrefWork,
    CrossrefClient,
)
from paper_feed.core.models import PaperItem


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_crossref_response() -> Dict[str, Any]:
    """Sample CrossRef API response with complete fields."""
    return {
        "DOI": "10.1038/nature.2024.12345",
        "title": ["A Comprehensive Study on Machine Learning"],
        "author": [
            {"given": "John", "family": "Doe"},
            {"given": "Jane", "family": "Smith"},
            {"family": "Johnson"},  # Family only
        ],
        "container-title": ["Nature Reviews Machine Learning"],
        "published": {"date-parts": [[2024, 3, 15]]},
        "published-print": {"date-parts": [[2024, 3, 20]]},
        "published-online": {"date-parts": [[2024, 3, 10]]},
        "volume": "5",
        "issue": "3",
        "page": "123-145",
        "abstract": "<p>This is an <b>abstract</b> with HTML.</p>",
        "URL": "https://doi.org/10.1038/nature.2024.12345",
        "publisher": "Nature Publishing Group",
        "ISSN": ["1234-5678"],
        "type": "journal-article",
        "subject": ["Computer Science", "Machine Learning", "Artificial Intelligence"],
        "funder": [
            {
                "name": "National Science Foundation",
                "award": ["NSF-123456", "NSF-789012"],
            },
            {
                "name": "European Research Council",
                "award": ["ERC-445566"],
            },
        ],
        "reference": [{"key": "ref1"}, {"key": "ref2"}],  # 2 references
        "link": [
            {
                "URL": "https://example.com/paper.pdf",
                "content-type": "application/pdf",
            },
            {
                "URL": "https://example.com/paper.html",
                "content-type": "text/html",
            },
        ],
    }


@pytest.fixture
def minimal_crossref_response() -> Dict[str, Any]:
    """Minimal CrossRef API response with only required fields."""
    return {
        "DOI": "10.1234/test.2024.001",
        "title": ["Simple Paper"],
        "type": "journal-article",
    }


@pytest.fixture
def sample_paper_item() -> PaperItem:
    """Sample PaperItem for enrichment testing."""
    return PaperItem(
        title="Original Title",
        source="Test Source",
        source_type="rss",
        authors=["Original Author"],
        abstract="Original abstract",
        doi="10.1234/original",
        url="https://example.com/original",
    )


@pytest.fixture
def minimal_paper_item() -> PaperItem:
    """Minimal PaperItem for enrichment testing."""
    return PaperItem(
        title="Machine Learning Study",
        source="Test Source",
        source_type="rss",
    )


# ============================================================================
# Tests for _clean_doi()
# ============================================================================


class TestCleanDOI:
    """Tests for DOI cleaning function."""

    def test_clean_doi_https_prefix(self):
        """Test stripping https://doi.org/ prefix."""
        doi = "https://doi.org/10.1038/nature.2024.12345"
        assert _clean_doi(doi) == "10.1038/nature.2024.12345"

    def test_clean_doi_http_prefix(self):
        """Test stripping http://doi.org/ prefix."""
        doi = "http://doi.org/10.1234/test"
        assert _clean_doi(doi) == "10.1234/test"

    def test_clean_doi_doi_prefix(self):
        """Test stripping doi: prefix."""
        doi = "doi:10.1038/test.2024"
        assert _clean_doi(doi) == "10.1038/test.2024"

    def test_clean_doi_bare_doi(self):
        """Test passing through bare DOI."""
        doi = "10.1038/nature.2024.12345"
        assert _clean_doi(doi) == "10.1038/nature.2024.12345"

    def test_clean_doi_with_whitespace(self):
        """Test stripping whitespace from bare DOI."""
        doi = "  10.1038/nature.2024  "
        assert _clean_doi(doi) == "10.1038/nature.2024"


# ============================================================================
# Tests for CrossrefWork.from_api_response()
# ============================================================================


class TestCrossrefWorkFromResponse:
    """Tests for CrossrefWork.from_api_response()."""

    def test_parse_complete_response(self, sample_crossref_response):
        """Test parsing complete CrossRef response with all fields."""
        work = CrossrefWork.from_api_response(sample_crossref_response)

        assert work.doi == "10.1038/nature.2024.12345"
        assert work.title == "A Comprehensive Study on Machine Learning"
        assert len(work.authors) == 3
        assert work.journal == "Nature Reviews Machine Learning"
        assert work.year == 2024
        assert work.volume == "5"
        assert work.issue == "3"
        assert work.pages == "123-145"
        assert work.abstract is not None
        assert "abstract" in work.abstract.lower()
        assert work.url == "https://doi.org/10.1038/nature.2024.12345"
        assert work.publisher == "Nature Publishing Group"
        assert work.item_type == "journalArticle"
        assert len(work.subjects) == 3
        assert len(work.funders) == 2
        assert work.citation_count == 2
        assert work.pdf_url == "https://example.com/paper.pdf"

    def test_parse_minimal_response(self, minimal_crossref_response):
        """Test parsing minimal CrossRef response."""
        work = CrossrefWork.from_api_response(minimal_crossref_response)

        assert work.doi == "10.1234/test.2024.001"
        assert work.title == "Simple Paper"
        assert work.authors == []
        assert work.journal == ""
        assert work.year is None
        assert work.abstract is None
        assert work.item_type == "journalArticle"
        assert work.subjects == []
        assert work.funders == []
        assert work.citation_count is None

    def test_author_extraction_given_and_family(self, sample_crossref_response):
        """Test author extraction with given and family names."""
        work = CrossrefWork.from_api_response(sample_crossref_response)

        # First author: given + family
        assert "Doe, John" in work.authors
        assert "Smith, Jane" in work.authors

    def test_author_extraction_family_only(self, sample_crossref_response):
        """Test author extraction with family name only."""
        work = CrossrefWork.from_api_response(sample_crossref_response)

        # Third author: family only
        assert "Johnson" in work.authors

    def test_author_extraction_name_field(self):
        """Test author extraction with name field."""
        response = {
            "title": ["Test"],
            "author": [{"name": "John Doe"}],
        }
        work = CrossrefWork.from_api_response(response)

        assert "John Doe" in work.authors

    def test_year_extraction_published(self, sample_crossref_response):
        """Test year extraction from published field."""
        work = CrossrefWork.from_api_response(sample_crossref_response)

        # Should use published (first priority)
        assert work.year == 2024

    def test_year_extraction_published_print(self):
        """Test year extraction from published-print fallback."""
        response = {
            "title": ["Test"],
            "published-print": {"date-parts": [[2023, 6, 1]]},
        }
        work = CrossrefWork.from_api_response(response)

        assert work.year == 2023

    def test_year_extraction_published_online(self):
        """Test year extraction from published-online fallback."""
        response = {
            "title": ["Test"],
            "published-online": {"date-parts": [[2022, 3, 15]]},
        }
        work = CrossrefWork.from_api_response(response)

        assert work.year == 2022

    def test_type_mapping_journal_article(self):
        """Test type mapping for journal-article."""
        response = {"title": ["Test"], "type": "journal-article"}
        work = CrossrefWork.from_api_response(response)

        assert work.item_type == "journalArticle"

    def test_type_mapping_conference_paper(self):
        """Test type mapping for proceedings-article."""
        response = {"title": ["Test"], "type": "proceedings-article"}
        work = CrossrefWork.from_api_response(response)

        assert work.item_type == "conferencePaper"

    def test_type_mapping_book_chapter(self):
        """Test type mapping for book-chapter."""
        response = {"title": ["Test"], "type": "book-chapter"}
        work = CrossrefWork.from_api_response(response)

        assert work.item_type == "bookSection"

    def test_type_mapping_book(self):
        """Test type mapping for book."""
        response = {"title": ["Test"], "type": "book"}
        work = CrossrefWork.from_api_response(response)

        assert work.item_type == "book"

    def test_type_mapping_report(self):
        """Test type mapping for report."""
        response = {"title": ["Test"], "type": "report"}
        work = CrossrefWork.from_api_response(response)

        assert work.item_type == "report"

    def test_type_mapping_dataset(self):
        """Test type mapping for dataset."""
        response = {"title": ["Test"], "type": "dataset"}
        work = CrossrefWork.from_api_response(response)

        assert work.item_type == "dataset"

    def test_type_mapping_dissertation(self):
        """Test type mapping for dissertation."""
        response = {"title": ["Test"], "type": "dissertation"}
        work = CrossrefWork.from_api_response(response)

        assert work.item_type == "thesis"

    def test_type_mapping_preprint(self):
        """Test type mapping for posted-content."""
        response = {"title": ["Test"], "type": "posted-content"}
        work = CrossrefWork.from_api_response(response)

        assert work.item_type == "preprint"

    def test_type_mapping_unknown(self):
        """Test type mapping for unknown types defaults to journalArticle."""
        response = {"title": ["Test"], "type": "unknown-type"}
        work = CrossrefWork.from_api_response(response)

        assert work.item_type == "journalArticle"

    def test_funder_extraction_with_awards(self, sample_crossref_response):
        """Test funder extraction with award numbers."""
        work = CrossrefWork.from_api_response(sample_crossref_response)

        assert len(work.funders) == 2
        assert any("National Science Foundation" in f for f in work.funders)
        assert any("NSF-123456" in f for f in work.funders)
        assert any("European Research Council" in f for f in work.funders)

    def test_pdf_url_extraction(self, sample_crossref_response):
        """Test PDF URL extraction from links."""
        work = CrossrefWork.from_api_response(sample_crossref_response)

        assert work.pdf_url == "https://example.com/paper.pdf"

    def test_pdf_url_missing(self):
        """Test when no PDF link is available."""
        response = {
            "title": ["Test"],
            "link": [
                {"URL": "https://example.com/paper.html", "content-type": "text/html"}
            ],
        }
        work = CrossrefWork.from_api_response(response)

        assert work.pdf_url is None

    def test_url_from_doi_when_missing(self):
        """Test URL construction from DOI when not provided."""
        response = {"title": ["Test"], "DOI": "10.1234/test"}
        work = CrossrefWork.from_api_response(response)

        assert work.url == "https://doi.org/10.1234/test"

    def test_url_provided_in_response(self):
        """Test using provided URL instead of constructing from DOI."""
        response = {
            "title": ["Test"],
            "DOI": "10.1234/test",
            "URL": "https://custom.example.com/paper",
        }
        work = CrossrefWork.from_api_response(response)

        assert work.url == "https://custom.example.com/paper"

    def test_abstract_cleaning(self, sample_crossref_response):
        """Test that abstract HTML is cleaned."""
        work = CrossrefWork.from_api_response(sample_crossref_response)

        # Should remove HTML tags and clean
        assert work.abstract is not None
        assert "<p>" not in work.abstract
        assert "<b>" not in work.abstract
        assert work.abstract  # Should not be empty


# ============================================================================
# Tests for CrossrefClient
# ============================================================================


class TestCrossrefClientInit:
    """Tests for CrossrefClient.__init__()."""

    @patch("paper_feed.sources.crossref.get_crossref_config")
    def test_init_with_email_param(self, mock_config):
        """Test initialization with explicit email parameter."""
        mock_config.return_value = {}
        client = CrossrefClient(email="test@example.com")

        assert client.email == "test@example.com"
        # Config is still called for other settings (api_base, timeout, etc.)
        mock_config.assert_called_once()

    @patch("paper_feed.sources.crossref.get_crossref_config")
    def test_init_from_config(self, mock_config):
        """Test initialization loading email from config."""
        mock_config.return_value = {"email": "config@example.com"}

        client = CrossrefClient()

        assert client.email == "config@example.com"
        mock_config.assert_called_once()

    @patch("paper_feed.sources.crossref.get_crossref_config")
    def test_init_no_email(self, mock_config):
        """Test initialization with no email (config returns None)."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        assert client.email is None


class TestCrossrefClientSearchByTitle:
    """Tests for CrossrefClient.search_by_title()."""

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_search_by_title_success(self, mock_config, sample_crossref_response):
        """Test successful title search."""
        mock_config.return_value = {"email": "test@example.com"}

        client = CrossrefClient(email="test@example.com")

        # Mock the httpx.AsyncClient
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"items": [sample_crossref_response]}
        }
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            results = await client.search_by_title("machine learning")

        assert len(results) == 1
        assert results[0].title == "A Comprehensive Study on Machine Learning"
        assert results[0].doi == "10.1038/nature.2024.12345"

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_search_by_title_empty_results(self, mock_config):
        """Test title search with no results."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"items": []}}
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            results = await client.search_by_title("nonexistent paper xyz")

        assert len(results) == 0

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_search_by_title_http_error(self, mock_config):
        """Test search handling HTTP errors gracefully."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection error")

        with patch.object(client, "_get_client", return_value=mock_client):
            results = await client.search_by_title("test paper")

        assert len(results) == 0

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_search_by_title_custom_rows(self, mock_config):
        """Test search with custom row limit."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"items": []}}
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            await client.search_by_title("test", rows=10)

        # Verify rows parameter was passed
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args[1]
        assert call_kwargs["params"]["rows"] == 10


class TestCrossrefClientGetByDOI:
    """Tests for CrossrefClient.get_by_doi()."""

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_get_by_doi_success(self, mock_config, sample_crossref_response):
        """Test successful DOI lookup."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": sample_crossref_response}
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            work = await client.get_by_doi("10.1038/nature.2024.12345")

        assert work is not None
        assert work.doi == "10.1038/nature.2024.12345"
        assert work.title == "A Comprehensive Study on Machine Learning"

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_get_by_doi_404_not_found(self, mock_config):
        """Test DOI lookup with 404 response."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = Exception("404 Not Found")

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.get.side_effect = Exception("404 Not Found")

        with patch.object(client, "_get_client", return_value=mock_client):
            work = await client.get_by_doi("10.invalid/notfound")

        assert work is None

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_get_by_doi_cleans_prefix(self, mock_config):
        """Test that DOI prefix is cleaned before lookup."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"DOI": "10.1234/test", "title": ["Test"]}
        }
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            await client.get_by_doi("https://doi.org/10.1234/test")

        # Verify the clean DOI was used in the request (URL-encoded)
        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args[0]
        # DOI is URL-encoded: 10.1234/test → 10.1234%2Ftest
        assert "10.1234" in call_args[0]
        assert "test" in call_args[0]


class TestCrossrefClientFindBestMatch:
    """Tests for CrossrefClient.find_best_match()."""

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_find_best_match_above_threshold(
        self, mock_config, sample_crossref_response
    ):
        """Test finding best match when score is above threshold."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        # Create response with exact title match
        response = sample_crossref_response.copy()
        response["title"] = ["A Comprehensive Study on Machine Learning"]

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"items": [response]}}
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            work = await client.find_best_match(
                "A Comprehensive Study on Machine Learning", threshold=0.8
            )

        assert work is not None
        assert work.title == "A Comprehensive Study on Machine Learning"

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_find_best_match_below_threshold(
        self, mock_config, sample_crossref_response
    ):
        """Test finding best match when score is below threshold."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"items": [sample_crossref_response]}
        }
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            # Very different title should fail threshold
            work = await client.find_best_match("completely different", threshold=0.9)

        assert work is None

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_find_best_match_no_results(self, mock_config):
        """Test finding best match with no search results."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"items": []}}
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            work = await client.find_best_match("any title")

        assert work is None


class TestCrossrefClientEnrichPaper:
    """Tests for CrossrefClient.enrich_paper()."""

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_enrich_paper_by_doi(
        self, mock_config, sample_crossref_response, minimal_paper_item
    ):
        """Test enrichment using DOI lookup."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()
        paper = minimal_paper_item.model_copy(update={"doi": "10.1038/test"})

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": sample_crossref_response}
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            enriched = await client.enrich_paper(paper)

        # Should have added fields
        assert enriched.abstract is not None
        assert len(enriched.authors) > 0
        assert enriched.pdf_url == "https://example.com/paper.pdf"

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_enrich_paper_by_title_search(
        self, mock_config, sample_crossref_response
    ):
        """Test enrichment using title search."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()
        paper = PaperItem(
            title="Machine Learning",
            source="Test",
            source_type="rss",
        )

        # Mock search_by_title to return a work
        mock_work = CrossrefWork.from_api_response(sample_crossref_response)

        with patch.object(client, "find_best_match", return_value=mock_work):
            enriched = await client.enrich_paper(paper)

        assert enriched.abstract is not None
        assert len(enriched.authors) > 0

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_enrich_paper_does_not_overwrite_existing(
        self, mock_config, sample_crossref_response
    ):
        """Test that enrichment doesn't overwrite existing fields."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()
        original_abstract = "My original abstract"
        original_authors = ["My Author"]
        paper = PaperItem(
            title="Test Paper",
            source="Test",
            source_type="rss",
            abstract=original_abstract,
            authors=original_authors,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": sample_crossref_response}
        mock_response.raise_for_status.return_value = None

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response

        with patch.object(client, "_get_client", return_value=mock_client):
            enriched = await client.enrich_paper(paper)

        # Should not overwrite existing fields
        assert enriched.abstract == original_abstract
        assert enriched.authors == original_authors

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_enrich_paper_stores_crossref_metadata(
        self, mock_config, sample_crossref_response, minimal_paper_item
    ):
        """Test that enrichment stores CrossRef metadata."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        # minimal_paper_item has no DOI, so enrich_paper uses find_best_match
        mock_work = CrossrefWork.from_api_response(sample_crossref_response)

        with patch.object(client, "find_best_match", return_value=mock_work):
            enriched = await client.enrich_paper(minimal_paper_item)

        # Should have crossref metadata stored
        assert "crossref" in enriched.metadata
        crossref_data = enriched.metadata["crossref"]
        assert "journal" in crossref_data
        assert "publisher" in crossref_data
        assert "volume" in crossref_data
        assert "issue" in crossref_data
        assert "pages" in crossref_data
        assert "funders" in crossref_data
        assert "subjects" in crossref_data

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_enrich_paper_no_match(self, mock_config, minimal_paper_item):
        """Test enrichment when no CrossRef match is found."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        # Mock both DOI lookup and title search to return None
        with patch.object(client, "get_by_doi", return_value=None):
            with patch.object(client, "find_best_match", return_value=None):
                enriched = await client.enrich_paper(minimal_paper_item)

        # Should return unchanged paper
        assert enriched == minimal_paper_item

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_enrich_paper_fills_missing_doi(
        self, mock_config, sample_crossref_response
    ):
        """Test that enrichment fills missing DOI."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()
        paper = PaperItem(
            title="Test Paper",
            source="Test",
            source_type="rss",
            # No DOI
        )

        # Paper has no DOI → enrich_paper uses find_best_match
        mock_work = CrossrefWork.from_api_response(sample_crossref_response)

        with patch.object(client, "find_best_match", return_value=mock_work):
            enriched = await client.enrich_paper(paper)

        assert enriched.doi == "10.1038/nature.2024.12345"

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_enrich_paper_fills_missing_url(
        self, mock_config, sample_crossref_response
    ):
        """Test that enrichment fills missing URL."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()
        paper = PaperItem(
            title="Test Paper",
            source="Test",
            source_type="rss",
            # No URL
        )

        # Paper has no DOI → enrich_paper uses find_best_match
        mock_work = CrossrefWork.from_api_response(sample_crossref_response)

        with patch.object(client, "find_best_match", return_value=mock_work):
            enriched = await client.enrich_paper(paper)

        assert enriched.url == "https://doi.org/10.1038/nature.2024.12345"

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_enrich_paper_fills_missing_published_date(
        self, mock_config, sample_crossref_response
    ):
        """Test that enrichment fills missing published_date."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()
        paper = PaperItem(
            title="Test Paper",
            source="Test",
            source_type="rss",
            # No published_date
        )

        # Paper has no DOI → enrich_paper uses find_best_match
        mock_work = CrossrefWork.from_api_response(sample_crossref_response)

        with patch.object(client, "find_best_match", return_value=mock_work):
            enriched = await client.enrich_paper(paper)

        assert enriched.published_date == date(2024, 1, 1)


class TestCrossrefClientClose:
    """Tests for CrossrefClient.close()."""

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_close_closes_client(self, mock_config):
        """Test that close() closes the httpx client."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        # Set up a mock client
        mock_http_client = AsyncMock()
        client._client = mock_http_client

        await client.close()

        # Verify aclose was called
        mock_http_client.aclose.assert_called_once()
        assert client._client is None

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_close_when_no_client_exists(self, mock_config):
        """Test close() when client was never initialized."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        # Should not raise an error
        await client.close()

        assert client._client is None


# ============================================================================
# Integration-like tests with helpers
# ============================================================================


class TestCrossrefIntegration:
    """Integration-style tests combining multiple components."""

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_full_enrichment_workflow(
        self, mock_config, sample_crossref_response
    ):
        """Test complete enrichment workflow: init → enrich → close."""
        mock_config.return_value = {"email": "test@example.com"}

        client = CrossrefClient()
        paper = PaperItem(
            title="A New Study",
            source="Test",
            source_type="rss",
        )

        # Paper has no DOI → enrich_paper uses find_best_match
        mock_work = CrossrefWork.from_api_response(sample_crossref_response)

        with patch.object(client, "find_best_match", return_value=mock_work):
            enriched = await client.enrich_paper(paper)
            await client.close()

        # Verify enrichment occurred
        assert enriched.abstract is not None
        assert len(enriched.authors) > 0
        assert enriched.doi is not None

    @pytest.mark.asyncio
    @patch("paper_feed.sources.crossref.get_crossref_config")
    async def test_multiple_papers_enrichment(
        self, mock_config, sample_crossref_response
    ):
        """Test enriching multiple papers with a single client."""
        mock_config.return_value = {"email": None}

        client = CrossrefClient()

        papers = [
            PaperItem(title="Paper 1", source="Test", source_type="rss"),
            PaperItem(title="Paper 2", source="Test", source_type="rss"),
            PaperItem(title="Paper 3", source="Test", source_type="rss"),
        ]

        # Papers have no DOI → enrich_paper uses find_best_match
        mock_work = CrossrefWork.from_api_response(sample_crossref_response)

        with patch.object(client, "find_best_match", return_value=mock_work):
            enriched_papers = []
            for paper in papers:
                enriched = await client.enrich_paper(paper)
                enriched_papers.append(enriched)
            await client.close()

        # All papers should be enriched
        assert len(enriched_papers) == 3
