"""Unit tests for OpenAlex source module."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.sources.openalex import (
    _clean_doi,
    _reconstruct_abstract,
    OpenAlexWork,
    OpenAlexClient,
)
from src.models.responses import PaperItem


class Test_CleanDOI:
    """Test cases for _clean_doi function."""

    def test_clean_doi_https_prefix(self):
        """Test stripping https://doi.org/ prefix."""
        result = _clean_doi("https://doi.org/10.1234/test")
        assert result == "10.1234/test"

    def test_clean_doi_http_prefix(self):
        """Test stripping http://doi.org/ prefix."""
        result = _clean_doi("http://doi.org/10.5678/example")
        assert result == "10.5678/example"

    def test_clean_doi_doi_prefix(self):
        """Test stripping doi: prefix."""
        result = _clean_doi("doi:10.9999/special")
        assert result == "10.9999/special"

    def test_clean_doi_bare_doi(self):
        """Test passing through bare DOI without prefix."""
        result = _clean_doi("10.1111/pure")
        assert result == "10.1111/pure"

    def test_clean_doi_with_whitespace(self):
        """Test stripping whitespace from bare DOI."""
        result = _clean_doi("  10.2222/spaces  ")
        assert result == "10.2222/spaces"


class Test_ReconstructAbstract:
    """Test cases for _reconstruct_abstract function."""

    def test_reconstruct_abstract_simple(self):
        """Test reconstructing simple inverted index."""
        inverted_index = {
            "This": [0],
            "is": [1],
            "a": [2],
            "test": [3],
        }
        result = _reconstruct_abstract(inverted_index)
        assert result is not None
        # Result should be cleaned by clean_abstract, so verify presence of words
        assert "This" in result
        assert "is" in result
        assert "a" in result
        assert "test" in result

    def test_reconstruct_abstract_with_repeated_words(self):
        """Test reconstructing abstract with repeated words."""
        inverted_index = {
            "The": [0, 5],
            "cat": [1],
            "sat": [2],
            "on": [3],
            "mat": [4],
        }
        result = _reconstruct_abstract(inverted_index)
        assert result is not None
        assert "cat" in result
        assert "mat" in result

    def test_reconstruct_abstract_empty_dict(self):
        """Test that empty dict returns None."""
        result = _reconstruct_abstract({})
        assert result is None

    def test_reconstruct_abstract_none_input(self):
        """Test that None input returns None."""
        result = _reconstruct_abstract(None)
        assert result is None

    def test_reconstruct_abstract_invalid_data(self):
        """Test that invalid data returns None."""
        result = _reconstruct_abstract({"word": 123})  # type: ignore[invalid-argument-type]
        assert result is None


class TestOpenAlexWorkFromAPIResponse:
    """Test cases for OpenAlexWork.from_api_response class method."""

    def test_from_api_response_complete(self):
        """Test parsing complete API response."""
        data = {
            "doi": "https://doi.org/10.1234/test",
            "title": "Complete Test Paper",
            "authorships": [
                {"author": {"display_name": "John Doe"}},
                {"author": {"display_name": "Jane Smith"}},
            ],
            "primary_location": {"source": {"display_name": "Nature"}},
            "publication_year": 2024,
            "biblio": {
                "volume": "42",
                "issue": "1",
                "first_page": "10",
                "last_page": "20",
            },
            "abstract_inverted_index": {
                "This": [0],
                "is": [1],
                "test": [2],
            },
            "type": "article",
            "cited_by_count": 42,
            "concepts": [
                {"display_name": "Chemistry", "score": 0.8},
                {"display_name": "Art", "score": 0.1},
            ],
            "id": "https://openalex.org/W12345",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.doi == "10.1234/test"
        assert work.title == "Complete Test Paper"
        assert work.authors == ["John Doe", "Jane Smith"]
        assert work.journal == "Nature"
        assert work.year == 2024
        assert work.volume == "42"
        assert work.issue == "1"
        assert work.pages == "10-20"
        assert work.abstract is not None
        assert work.item_type == "journalArticle"
        assert work.cited_by_count == 42
        assert "Chemistry" in work.concepts
        assert "Art" not in work.concepts  # Score 0.1 < 0.3
        assert work.raw_data == data

    def test_from_api_response_minimal(self):
        """Test parsing minimal API response."""
        data = {
            "title": "Minimal Paper",
            "display_name": "Minimal Paper",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.title == "Minimal Paper"
        assert work.authors == []
        assert work.doi == ""
        assert work.journal is None
        assert work.year is None
        assert work.abstract is None
        assert work.item_type == "journalArticle"

    def test_from_api_response_author_extraction(self):
        """Test extracting authors from authorships."""
        data = {
            "title": "Auth Test",
            "authorships": [
                {"author": {"display_name": "Author One"}},
                {"author": {"display_name": "Author Two"}},
                {"author": {}},  # Missing display_name
            ],
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.authors == ["Author One", "Author Two"]

    def test_from_api_response_year_extraction(self):
        """Test extracting year from publication_year."""
        data = {
            "title": "Year Test",
            "publication_year": 2023,
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.year == 2023

    def test_from_api_response_pages_both_endpoints(self):
        """Test page range with first_page and last_page."""
        data = {
            "title": "Pages Test",
            "biblio": {
                "first_page": "100",
                "last_page": "110",
            },
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.pages == "100-110"

    def test_from_api_response_pages_first_only(self):
        """Test page range with only first_page."""
        data = {
            "title": "First Page Only",
            "biblio": {
                "first_page": "200",
            },
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.pages == "200"

    def test_from_api_response_pages_none(self):
        """Test that pages is None when no biblio."""
        data = {
            "title": "No Pages",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.pages is None

    def test_from_api_response_journal_extraction(self):
        """Test extracting journal from primary_location."""
        data = {
            "title": "Journal Test",
            "primary_location": {"source": {"display_name": "Science"}},
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.journal == "Science"

    def test_from_api_response_journal_missing(self):
        """Test that journal is None when no primary_location."""
        data = {
            "title": "No Journal",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.journal is None

    def test_from_api_response_concepts_filtering(self):
        """Test filtering concepts by score > 0.3."""
        data = {
            "title": "Concepts Test",
            "concepts": [
                {"display_name": "High Score", "score": 0.95},
                {"display_name": "Threshold", "score": 0.30},
                {"display_name": "Just Below", "score": 0.299},
                {"display_name": "Low Score", "score": 0.05},
            ],
        }

        work = OpenAlexWork.from_api_response(data)

        assert "High Score" in work.concepts
        assert "Threshold" not in work.concepts  # score == 0.3, not > 0.3
        assert "Just Below" not in work.concepts
        assert "Low Score" not in work.concepts

    def test_from_api_response_type_mapping_article(self):
        """Test type mapping for article."""
        data = {
            "title": "Article",
            "type": "article",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.item_type == "journalArticle"

    def test_from_api_response_type_mapping_book(self):
        """Test type mapping for book."""
        data = {
            "title": "Book",
            "type": "book",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.item_type == "book"

    def test_from_api_response_type_mapping_book_chapter(self):
        """Test type mapping for book-chapter."""
        data = {
            "title": "Chapter",
            "type": "book-chapter",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.item_type == "bookSection"

    def test_from_api_response_type_mapping_proceedings(self):
        """Test type mapping for proceedings."""
        data = {
            "title": "Proceedings",
            "type": "proceedings-article",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.item_type == "conferencePaper"

    def test_from_api_response_type_unknown(self):
        """Test that unknown type defaults to journalArticle."""
        data = {
            "title": "Unknown Type",
            "type": "unknown_type",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.item_type == "journalArticle"

    def test_from_api_response_cited_by_zero_becomes_none(self):
        """Test that cited_by_count of 0 becomes None."""
        data = {
            "title": "Uncited",
            "cited_by_count": 0,
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.cited_by_count is None

    def test_from_api_response_cited_by_positive(self):
        """Test that positive cited_by_count is preserved."""
        data = {
            "title": "Cited",
            "cited_by_count": 42,
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.cited_by_count == 42

    def test_from_api_response_doi_url_extraction(self):
        """Test extracting DOI from https://doi.org/ URL format."""
        data = {
            "title": "DOI Test",
            "doi": "https://doi.org/10.1234/test.article",
        }

        work = OpenAlexWork.from_api_response(data)

        assert work.doi == "10.1234/test.article"


class TestOpenAlexClientInit:
    """Test cases for OpenAlexClient initialization."""

    def test_client_init_with_email(self):
        """Test client initialization with explicit email."""
        client = OpenAlexClient(email="user@example.com")

        assert client.email == "user@example.com"

    def test_client_init_without_email_from_config(self):
        """Test client initialization loading email from config."""
        with patch("src.sources.openalex.get_openalex_config") as mock_config:
            mock_config.return_value = {"email": "config@example.com"}

            client = OpenAlexClient(email=None)

            assert client.email == "config@example.com"

    def test_client_init_without_email_none_config(self):
        """Test client initialization when config returns None."""
        with patch("src.sources.openalex.get_openalex_config") as mock_config:
            mock_config.return_value = {"email": None}

            client = OpenAlexClient(email=None)

            assert client.email is None


class TestOpenAlexClientHeaders:
    """Test cases for OpenAlexClient._headers property."""

    def test_headers_with_email(self):
        """Test that headers include User-Agent and mailto when email provided."""
        client = OpenAlexClient(email="user@example.com")

        headers = client._headers

        assert "User-Agent" in headers
        assert "feedder-mcp" in headers["User-Agent"]
        assert "user@example.com" in headers["User-Agent"]
        assert "mailto" in headers
        assert headers["mailto"] == "user@example.com"

    @patch("src.sources.openalex.get_openalex_config")
    def test_headers_without_email(self, mock_config):
        """Test that headers use default email when not provided."""
        mock_config.return_value = {}
        client = OpenAlexClient(email=None)

        headers = client._headers

        assert "User-Agent" in headers
        assert "noreply@example.com" in headers["User-Agent"]


class TestOpenAlexClientSearchByTitle:
    """Test cases for OpenAlexClient.search_by_title method."""

    @pytest.mark.asyncio
    async def test_search_by_title_success(self):
        """Test successful title search with mocked HTTP response."""
        client = OpenAlexClient(email="test@example.com")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Found Paper",
                    "doi": "https://doi.org/10.1111/test",
                    "authorships": [],
                    "publication_year": 2024,
                    "type": "article",
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "src.sources.openalex.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client_instance

            results = await client.search_by_title("Test Paper")

            assert len(results) == 1
            assert results[0].title == "Found Paper"
            assert results[0].doi == "10.1111/test"

    @pytest.mark.asyncio
    async def test_search_by_title_empty_results(self):
        """Test title search returning empty results."""
        client = OpenAlexClient(email="test@example.com")

        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "src.sources.openalex.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client_instance

            results = await client.search_by_title("Nonexistent Paper")

            assert results == []

    @pytest.mark.asyncio
    async def test_search_by_title_http_error(self):
        """Test title search handling HTTP error."""
        client = OpenAlexClient(email="test@example.com")

        with patch(
            "src.sources.openalex.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(side_effect=Exception("Network error"))
            mock_client_class.return_value = mock_client_instance

            results = await client.search_by_title("Test Paper")

            assert results == []

    @pytest.mark.asyncio
    async def test_search_by_title_per_page_param(self):
        """Test that per_page parameter is passed correctly."""
        client = OpenAlexClient(email="test@example.com")

        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch(
            "src.sources.openalex.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client_instance

            await client.search_by_title("Test", per_page=10)

            # Verify get was called with correct params
            mock_client_instance.get.assert_called_once()
            call_args = mock_client_instance.get.call_args
            assert call_args.kwargs["params"]["per_page"] == 10


class TestOpenAlexClientGetByDOI:
    """Test cases for OpenAlexClient.get_by_doi method."""

    @pytest.mark.asyncio
    async def test_get_by_doi_success(self):
        """Test successful DOI lookup."""
        client = OpenAlexClient(email="test@example.com")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "title": "DOI Paper",
            "doi": "https://doi.org/10.2222/test",
            "publication_year": 2023,
            "type": "article",
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "src.sources.openalex.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client_instance

            work = await client.get_by_doi("10.2222/test")

            assert work is not None
            assert work.title == "DOI Paper"
            assert work.doi == "10.2222/test"

    @pytest.mark.asyncio
    async def test_get_by_doi_not_found(self):
        """Test DOI lookup returning 404."""
        client = OpenAlexClient(email="test@example.com")

        from httpx import HTTPStatusError, Request, Response

        error_response = Response(status_code=404)
        error = HTTPStatusError(
            "Not found", request=Request("GET", "/"), response=error_response
        )

        with patch(
            "src.sources.openalex.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(side_effect=error)
            mock_client_class.return_value = mock_client_instance

            work = await client.get_by_doi("10.9999/nonexistent")

            assert work is None

    @pytest.mark.asyncio
    async def test_get_by_doi_cleans_doi(self):
        """Test that get_by_doi cleans the DOI before lookup."""
        client = OpenAlexClient(email="test@example.com")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "title": "Test",
            "type": "article",
        }
        mock_response.raise_for_status = MagicMock()

        with patch(
            "src.sources.openalex.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client_instance

            await client.get_by_doi("https://doi.org/10.3333/test")

            # Verify the URL-encoded version was used
            call_args = mock_client_instance.get.call_args
            assert "10.3333" in str(call_args)


class TestOpenAlexClientFindBestMatch:
    """Test cases for OpenAlexClient.find_best_match method."""

    @pytest.mark.asyncio
    async def test_find_best_match_above_threshold(self):
        """Test finding best match when similarity above threshold."""
        client = OpenAlexClient(email="test@example.com")

        # Mock search_by_title to return multiple results
        works = [
            OpenAlexWork(
                title="Machine Learning Basics",
                doi="10.1111/ml",
            ),
            OpenAlexWork(
                title="Deep Learning Advanced",
                doi="10.2222/dl",
            ),
        ]

        with patch.object(
            client, "search_by_title", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = works

            best = await client.find_best_match("Machine Learning Basics")

            assert best is not None
            assert best.title == "Machine Learning Basics"

    @pytest.mark.asyncio
    async def test_find_best_match_below_threshold(self):
        """Test finding best match when similarity below threshold."""
        client = OpenAlexClient(email="test@example.com")

        works = [
            OpenAlexWork(
                title="Completely Different Paper",
                doi="10.1111/diff",
            ),
        ]

        with patch.object(
            client, "search_by_title", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = works

            best = await client.find_best_match("Machine Learning", threshold=0.8)

            assert best is None

    @pytest.mark.asyncio
    async def test_find_best_match_empty_results(self):
        """Test finding best match when search returns no results."""
        client = OpenAlexClient(email="test@example.com")

        with patch.object(
            client, "search_by_title", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = []

            best = await client.find_best_match("Any Paper")

            assert best is None

    @pytest.mark.asyncio
    async def test_find_best_match_picks_highest_similarity(self):
        """Test that find_best_match picks result with highest similarity."""
        client = OpenAlexClient(email="test@example.com")

        works = [
            OpenAlexWork(
                title="Machine Learning for Beginners",
                doi="10.1111/ml1",
            ),
            OpenAlexWork(
                title="Advanced Neural Networks",
                doi="10.2222/nn",
            ),
            OpenAlexWork(
                title="Machine Learning Fundamentals",
                doi="10.3333/ml2",
            ),
        ]

        with patch.object(
            client, "search_by_title", new_callable=AsyncMock
        ) as mock_search:
            mock_search.return_value = works

            best = await client.find_best_match(
                "Machine Learning Fundamentals", threshold=0.5
            )

            assert best is not None
            assert "Fundamentals" in best.title


class TestOpenAlexClientEnrichPaper:
    """Test cases for OpenAlexClient.enrich_paper method."""

    @pytest.mark.asyncio
    async def test_enrich_paper_fills_missing_fields(self):
        """Test that enrich_paper fills only missing fields."""
        client = OpenAlexClient(email="test@example.com")

        paper = PaperItem(
            title="Original Title",
            source="test",
            source_type="rss",
        )

        work = OpenAlexWork(
            title="Found Title",
            doi="10.1234/test",
            authors=["Author One"],
            abstract="Found abstract",
            journal="Nature",
            year=2024,
            concepts=["AI", "ML"],
        )

        with patch.object(client, "get_by_doi", new_callable=AsyncMock) as mock_doi:
            with patch.object(
                client, "find_best_match", new_callable=AsyncMock
            ) as mock_search:
                mock_doi.return_value = None
                mock_search.return_value = work

                enriched = await client.enrich_paper(paper)

                # Original title should be preserved
                assert enriched.title == "Original Title"
                # Missing fields should be filled
                assert enriched.abstract == "Found abstract"
                assert enriched.authors == ["Author One"]
                assert enriched.doi == "10.1234/test"

    @pytest.mark.asyncio
    async def test_enrich_paper_doi_lookup_first(self):
        """Test that enrich_paper tries DOI lookup first."""
        client = OpenAlexClient(email="test@example.com")

        paper = PaperItem(
            title="Test",
            doi="10.5555/existing",
            source="test",
            source_type="rss",
        )

        work = OpenAlexWork(
            title="Found",
            doi="10.5555/existing",
        )

        with patch.object(client, "get_by_doi", new_callable=AsyncMock) as mock_doi:
            mock_doi.return_value = work

            await client.enrich_paper(paper)

            # Should call get_by_doi with the existing DOI
            mock_doi.assert_called_once_with("10.5555/existing")

    @pytest.mark.asyncio
    async def test_enrich_paper_title_search_fallback(self):
        """Test that enrich_paper falls back to title search if DOI fails."""
        client = OpenAlexClient(email="test@example.com")

        paper = PaperItem(
            title="Test Paper",
            doi="10.6666/notfound",
            source="test",
            source_type="rss",
        )

        work = OpenAlexWork(
            title="Test Paper",
            abstract="Found by title",
        )

        with patch.object(client, "get_by_doi", new_callable=AsyncMock) as mock_doi:
            with patch.object(
                client, "find_best_match", new_callable=AsyncMock
            ) as mock_search:
                mock_doi.return_value = None
                mock_search.return_value = work

                enriched = await client.enrich_paper(paper)

                # Should call find_best_match since DOI lookup failed
                mock_search.assert_called_once_with("Test Paper")
                assert enriched.abstract == "Found by title"

    @pytest.mark.asyncio
    async def test_enrich_paper_stores_openalex_metadata(self):
        """Test that enrich_paper stores OpenAlex metadata."""
        client = OpenAlexClient(email="test@example.com")

        paper = PaperItem(
            title="Test",
            source="test",
            source_type="rss",
        )

        work = OpenAlexWork(
            title="Test",
            journal="Nature",
            cited_by_count=42,
            concepts=["AI"],
            volume="1",
            issue="2",
            pages="10-20",
            item_type="journalArticle",
        )

        with patch.object(client, "get_by_doi", new_callable=AsyncMock):
            with patch.object(
                client, "find_best_match", new_callable=AsyncMock
            ) as mock_search:
                mock_search.return_value = work

                enriched = await client.enrich_paper(paper)

                assert "openalex" in enriched.extra
                assert enriched.extra["openalex"]["cited_by_count"] == 42
                assert enriched.extra["openalex"]["concepts"] == ["AI"]
                # journal/volume/issue/pages are now mapped directly
                assert enriched.publication_title == "Nature"
                assert enriched.volume == "1"
                assert enriched.issue == "2"
                assert enriched.pages == "10-20"

    @pytest.mark.asyncio
    async def test_enrich_paper_no_match(self):
        """Test that enrich_paper returns original paper if no match found."""
        client = OpenAlexClient(email="test@example.com")

        paper = PaperItem(
            title="Unique Title",
            source="test",
            source_type="rss",
        )

        with patch.object(client, "get_by_doi", new_callable=AsyncMock) as mock_doi:
            with patch.object(
                client, "find_best_match", new_callable=AsyncMock
            ) as mock_search:
                mock_doi.return_value = None
                mock_search.return_value = None

                enriched = await client.enrich_paper(paper)

                # Should return paper with unmatched info recorded
                assert enriched.title == paper.title
                assert enriched.extra.get("openalex_unmatched") is not None

    @pytest.mark.asyncio
    async def test_enrich_paper_published_date_from_year(self):
        """Test that published_date is set from work.year."""
        client = OpenAlexClient(email="test@example.com")

        paper = PaperItem(
            title="Test",
            source="test",
            source_type="rss",
        )

        work = OpenAlexWork(
            title="Test",
            year=2023,
        )

        with patch.object(client, "get_by_doi", new_callable=AsyncMock):
            with patch.object(
                client, "find_best_match", new_callable=AsyncMock
            ) as mock_search:
                mock_search.return_value = work

                enriched = await client.enrich_paper(paper)

                assert enriched.published_date == date(2023, 1, 1)

    @pytest.mark.asyncio
    async def test_enrich_paper_url_from_work(self):
        """Test that url is filled from work.url."""
        client = OpenAlexClient(email="test@example.com")

        paper = PaperItem(
            title="Test",
            source="test",
            source_type="rss",
        )

        work = OpenAlexWork(
            title="Test",
            url="https://example.com/paper",
        )

        with patch.object(client, "get_by_doi", new_callable=AsyncMock):
            with patch.object(
                client, "find_best_match", new_callable=AsyncMock
            ) as mock_search:
                mock_search.return_value = work

                enriched = await client.enrich_paper(paper)

                assert enriched.url == "https://example.com/paper"


class TestOpenAlexClientClose:
    """Test cases for OpenAlexClient.close method."""

    @pytest.mark.asyncio
    async def test_close_closes_client(self):
        """Test that close() closes the HTTP client."""
        client = OpenAlexClient(email="test@example.com")

        # Create a mock client
        mock_client = AsyncMock()
        client._client = mock_client

        await client.close()

        mock_client.aclose.assert_called_once()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_when_no_client(self):
        """Test that close() works when client is None."""
        client = OpenAlexClient(email="test@example.com")

        # Should not raise any exception
        await client.close()

        assert client._client is None
