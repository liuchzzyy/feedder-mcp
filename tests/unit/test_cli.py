"""Unit tests for CLI module."""

import argparse
import asyncio
import json
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from src.client.cli import (
    _build_parser,
    _load_papers,
    _save_papers,
    _handle_fetch,
    _handle_filter,
    _handle_export,
    _handle_enrich,
    main,
)
from src.models.responses import PaperItem, FilterResult


# -------------------- Fixtures --------------------


@pytest.fixture
def sample_papers():
    """Create sample papers for testing."""
    return [
        PaperItem(
            title="Test Paper 1",
            authors=["Author One", "Author Two"],
            abstract="This is a test abstract about machine learning",
            published_date=date(2024, 1, 15),
            doi="10.1234/test1",
            url="https://example.com/paper1",
            pdf_url="https://example.com/paper1.pdf",
            source="arXiv",
            source_id="test-001",
            source_type="rss",
            extra={"raw_data": "sample1"},
        ),
        PaperItem(
            title="Test Paper 2",
            authors=["Author Three"],
            abstract="Another test abstract",
            published_date=date(2024, 2, 20),
            doi="10.1234/test2",
            url="https://example.com/paper2",
            source="Nature",
            source_id="test-002",
            source_type="email",
            extra={"raw_data": "sample2"},
        ),
    ]


@pytest.fixture
def sample_papers_json(tmp_path, sample_papers):
    """Create a temporary JSON file with sample papers."""
    filepath = tmp_path / "papers.json"
    _save_papers(sample_papers, str(filepath))
    return filepath


# -------------------- Tests: _build_parser --------------------


class TestBuildParser:
    """Tests for _build_parser function."""

    def test_parser_returns_argparse_instance(self):
        """Test that _build_parser returns an ArgumentParser."""
        parser = _build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parser_has_all_subcommands(self):
        """Test that parser has all 4 required subcommands."""
        parser = _build_parser()

        # Parse with each subcommand to verify they exist
        # fetch
        args = parser.parse_args(["fetch", "--output", "out.json"])
        assert args.command == "fetch"

        # filter
        args = parser.parse_args(
            ["filter", "--input", "in.json", "--output", "out.json"]
        )
        assert args.command == "filter"

        # export
        args = parser.parse_args(
            ["export", "--input", "in.json", "--output", "out.json"]
        )
        assert args.command == "export"

        # enrich
        args = parser.parse_args(
            ["enrich", "--input", "in.json", "--output", "out.json"]
        )
        assert args.command == "enrich"

    def test_fetch_parser_has_required_args(self):
        """Test fetch subcommand has required arguments."""
        parser = _build_parser()
        args = parser.parse_args(["fetch", "--output", "out.json"])

        assert hasattr(args, "output")
        assert args.output == "out.json"
        assert args.source == "rss"  # default
        assert args.since is not None

    def test_fetch_parser_accepts_optional_args(self):
        """Test fetch parser accepts optional arguments."""
        parser = _build_parser()
        args = parser.parse_args(
            [
                "fetch",
                "--source",
                "gmail",
                "--query",
                "is:unread",
                "--limit",
                "50",
                "--since",
                "2024-01-01",
                "--output",
                "out.json",
            ]
        )

        assert args.source == "gmail"
        assert args.query == "is:unread"
        assert args.limit == 50
        assert args.since == "2024-01-01"

    def test_filter_parser_has_required_args(self):
        """Test filter subcommand requires input and output."""
        parser = _build_parser()
        args = parser.parse_args(
            [
                "filter",
                "--input",
                "in.json",
                "--output",
                "out.json",
            ]
        )

        assert args.input == "in.json"
        assert args.output == "out.json"

    def test_filter_parser_accepts_filter_args(self):
        """Test filter parser accepts keyword filters."""
        parser = _build_parser()
        args = parser.parse_args(
            [
                "filter",
                "--input",
                "in.json",
                "--output",
                "out.json",
                "--keywords",
                "machine",
                "learning",
                "--exclude",
                "review",
                "--authors",
                "Author",
                "--min-date",
                "2024-01-01",
                "--has-pdf",
                "--no-ai",
            ]
        )

        assert args.keywords == ["machine", "learning"]
        assert args.exclude == ["review"]
        assert args.authors == ["Author"]
        assert args.min_date == "2024-01-01"
        assert args.has_pdf is True
        assert args.ai is False

    def test_export_parser_has_required_args(self):
        """Test export subcommand requires input and output."""
        parser = _build_parser()
        args = parser.parse_args(
            [
                "export",
                "--input",
                "in.json",
                "--output",
                "out.json",
            ]
        )

        assert args.input == "in.json"
        assert args.output == "out.json"
        assert args.format == "json"  # default
        assert args.include_metadata is True
        assert args.collection is None

    def test_export_parser_accepts_format_options(self):
        """Test export parser accepts different formats."""
        parser = _build_parser()

        for fmt in ["json", "zotero"]:
            args = parser.parse_args(
                [
                    "export",
                    "--input",
                    "in.json",
                    "--output",
                    "out.json",
                    "--format",
                    fmt,
                    "--no-metadata",
                    "--collection",
                    "ABCD1234",
                ]
            )

            assert args.format == fmt
            assert args.include_metadata is False
            assert args.collection == "ABCD1234"

    def test_enrich_parser_has_required_args(self):
        """Test enrich subcommand requires input and output."""
        parser = _build_parser()
        args = parser.parse_args(
            [
                "enrich",
                "--input",
                "in.json",
                "--output",
                "out.json",
            ]
        )

        assert args.input == "in.json"
        assert args.output == "out.json"
        assert args.source == "all"  # default
        assert args.concurrency == 5  # default

    def test_enrich_parser_accepts_options(self):
        """Test enrich parser accepts source and concurrency options."""
        parser = _build_parser()

        for source in ["crossref", "openalex", "all"]:
            args = parser.parse_args(
                [
                    "enrich",
                    "--input",
                    "in.json",
                    "--output",
                    "out.json",
                    "--source",
                    source,
                    "--concurrency",
                    "10",
                ]
            )

            assert args.source == source
            assert args.concurrency == 10


# -------------------- Tests: _load_papers --------------------


class TestLoadPapers:
    """Tests for _load_papers function."""

    def test_load_papers_from_valid_json(self, sample_papers_json):
        """Test loading papers from a valid JSON file."""
        papers = _load_papers(str(sample_papers_json))

        assert len(papers) == 2
        assert papers[0].title == "Test Paper 1"
        assert papers[1].title == "Test Paper 2"

    def test_load_papers_returns_paper_items(self, sample_papers_json):
        """Test that loaded papers are PaperItem instances."""
        papers = _load_papers(str(sample_papers_json))

        assert all(isinstance(p, PaperItem) for p in papers)

    def test_load_papers_missing_file_exits(self, tmp_path):
        """Test that loading missing file causes SystemExit."""
        missing_file = tmp_path / "missing.json"

        with pytest.raises(SystemExit) as exc_info:
            _load_papers(str(missing_file))

        assert exc_info.value.code == 1

    def test_load_papers_invalid_json_exits(self, tmp_path):
        """Test that loading invalid JSON causes SystemExit."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("{ invalid json }")

        with pytest.raises(SystemExit) as exc_info:
            _load_papers(str(invalid_file))

        assert exc_info.value.code == 1

    def test_load_papers_invalid_model_exits(self, tmp_path):
        """Test that invalid PaperItem data causes SystemExit."""
        invalid_data_file = tmp_path / "invalid_model.json"
        # Missing required 'title' field
        invalid_data_file.write_text(
            json.dumps([{"source": "test", "source_type": "rss"}])
        )

        with pytest.raises(SystemExit) as exc_info:
            _load_papers(str(invalid_data_file))

        assert exc_info.value.code == 1


# -------------------- Tests: _save_papers --------------------


class TestSavePapers:
    """Tests for _save_papers function."""

    def test_save_papers_creates_json_file(self, sample_papers, tmp_path):
        """Test that _save_papers creates a JSON file."""
        output_file = tmp_path / "output.json"
        _save_papers(sample_papers, str(output_file))

        assert output_file.exists()

    def test_save_papers_valid_json(self, sample_papers, tmp_path):
        """Test that saved papers form valid JSON."""
        output_file = tmp_path / "output.json"
        _save_papers(sample_papers, str(output_file))

        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[0]["title"] == "Test Paper 1"

    def test_save_papers_creates_parent_directories(self, sample_papers, tmp_path):
        """Test that _save_papers creates parent directories."""
        output_file = tmp_path / "subdir1" / "subdir2" / "papers.json"
        _save_papers(sample_papers, str(output_file))

        assert output_file.exists()
        assert output_file.parent.exists()

    def test_save_papers_converts_dates_to_strings(self, sample_papers, tmp_path):
        """Test that dates are converted to ISO format strings."""
        output_file = tmp_path / "output.json"
        _save_papers(sample_papers, str(output_file))

        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert data[0]["published_date"] == "2024-01-15"
        assert data[1]["published_date"] == "2024-02-20"

    def test_save_papers_empty_list(self, tmp_path):
        """Test saving an empty list of papers."""
        output_file = tmp_path / "empty.json"
        _save_papers([], str(output_file))

        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert data == []


# -------------------- Tests: _handle_fetch --------------------


class TestHandleFetch:
    """Tests for _handle_fetch handler."""

    @pytest.mark.asyncio
    async def test_handle_fetch_rss_source(self, tmp_path, sample_papers, capsys):
        """Test fetch handler with RSS source."""
        output_file = tmp_path / "papers.json"

        args = argparse.Namespace(
            source="rss",
            opml=None,
            limit=None,
            since=None,
            output=str(output_file),
        )

        with patch("src.sources.rss.RSSSource") as mock_rss_class:
            mock_source = AsyncMock()
            mock_source.fetch_papers.return_value = sample_papers
            mock_rss_class.return_value = mock_source

            with patch("src.client.cli.get_rss_config") as mock_config:
                mock_config.return_value = {"opml_path": "feeds/test.opml"}

                await _handle_fetch(args)

        # Verify papers were saved
        assert output_file.exists()
        papers = _load_papers(str(output_file))
        assert len(papers) == 2

        # Verify output message
        captured = capsys.readouterr()
        assert "Fetched 2 papers" in captured.out

    @pytest.mark.asyncio
    async def test_handle_fetch_rss_with_opml_arg(self, tmp_path, sample_papers):
        """Test fetch handler respects --opml argument."""
        output_file = tmp_path / "papers.json"

        args = argparse.Namespace(
            source="rss",
            opml="/custom/path.opml",
            limit=10,
            since=None,
            output=str(output_file),
        )

        with patch("src.sources.rss.RSSSource") as mock_rss_class:
            mock_source = AsyncMock()
            mock_source.fetch_papers.return_value = sample_papers
            mock_rss_class.return_value = mock_source

            await _handle_fetch(args)

            # Verify RSSSource was called with custom path
            mock_rss_class.assert_called_once_with("/custom/path.opml")

    @pytest.mark.asyncio
    async def test_handle_fetch_gmail_source(self, tmp_path, sample_papers, capsys):
        """Test fetch handler with Gmail source."""
        output_file = tmp_path / "papers.json"

        args = argparse.Namespace(
            source="gmail",
            query="is:unread",
            limit=None,
            since=None,
            output=str(output_file),
        )

        with patch("src.sources.gmail.GmailSource") as mock_gmail_class:
            mock_source = AsyncMock()
            mock_source.fetch_papers.return_value = sample_papers
            mock_gmail_class.return_value = mock_source

            await _handle_fetch(args)

            mock_gmail_class.assert_called_once_with(query="is:unread")

        assert output_file.exists()
        captured = capsys.readouterr()
        assert "Fetched 2 papers" in captured.out

    @pytest.mark.asyncio
    async def test_handle_fetch_gmail_default_query(self, tmp_path, sample_papers):
        """Test fetch handler uses default Gmail query."""
        output_file = tmp_path / "papers.json"

        args = argparse.Namespace(
            source="gmail",
            query=None,  # No query provided
            limit=None,
            since=None,
            output=str(output_file),
        )

        with patch("src.sources.gmail.GmailSource") as mock_gmail_class:
            mock_source = AsyncMock()
            mock_source.fetch_papers.return_value = sample_papers
            mock_gmail_class.return_value = mock_source

            await _handle_fetch(args)

            # Default query handled by GmailSource
            mock_gmail_class.assert_called_once_with(query=None)

    @pytest.mark.asyncio
    async def test_handle_fetch_with_since_date(self, tmp_path, sample_papers):
        """Test fetch handler parses --since date."""
        output_file = tmp_path / "papers.json"

        args = argparse.Namespace(
            source="rss",
            opml=None,
            limit=None,
            since="2024-01-01",
            output=str(output_file),
        )

        with patch("src.sources.rss.RSSSource") as mock_rss_class:
            mock_source = AsyncMock()
            mock_source.fetch_papers.return_value = sample_papers
            mock_rss_class.return_value = mock_source

            with patch("src.client.cli.get_rss_config") as mock_config:
                mock_config.return_value = {"opml_path": "feeds/test.opml"}

                await _handle_fetch(args)

            # Verify since was parsed as date
            call_args = mock_source.fetch_papers.call_args
            assert call_args.kwargs["since"] == date(2024, 1, 1)

    @pytest.mark.asyncio
    async def test_handle_fetch_invalid_source_exits(self, tmp_path):
        """Test fetch with invalid source causes exit."""
        output_file = tmp_path / "papers.json"

        args = argparse.Namespace(
            source="invalid",
            output=str(output_file),
            since=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            await _handle_fetch(args)

        assert exc_info.value.code == 1


# -------------------- Tests: _handle_filter --------------------


class TestHandleFilter:
    """Tests for _handle_filter handler."""

    @pytest.mark.asyncio
    async def test_handle_filter_autogenerates_keywords(
        self, sample_papers_json, tmp_path
    ):
        """Test filter handler auto-generates keywords when missing."""
        output_file = tmp_path / "filtered.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            keywords=None,
            exclude=None,
            authors=None,
            min_date=None,
            has_pdf=False,
            ai=True,
        )

        with patch(
            "src.ai.keyword_generator.KeywordGenerator.extract_keywords",
            new=AsyncMock(return_value=["auto", "keyword"]),
        ):
            with patch("src.filters.pipeline.FilterPipeline") as mock_pipeline_class:
                mock_pipeline = AsyncMock()
                result = FilterResult(
                    papers=[],
                    total_count=2,
                    passed_count=0,
                    rejected_count=2,
                )
                mock_pipeline.filter.return_value = result
                mock_pipeline_class.return_value = mock_pipeline

                await _handle_filter(args)

                call_args = mock_pipeline.filter.call_args
                criteria = call_args[0][1]
                assert criteria.keywords == ["auto", "keyword"]

    @pytest.mark.asyncio
    async def test_handle_filter_with_keywords(
        self, sample_papers_json, tmp_path, capsys
    ):
        """Test filter handler with keyword criteria."""
        output_file = tmp_path / "filtered.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            keywords=["machine", "learning"],
            exclude=None,
            authors=None,
            min_date=None,
            has_pdf=False,
            ai=True,
        )

        with patch("src.filters.pipeline.FilterPipeline") as mock_pipeline_class:
            mock_pipeline = AsyncMock()
            papers = _load_papers(str(sample_papers_json))
            result = FilterResult(
                papers=[papers[0]],
                total_count=1,
                passed_count=1,
                rejected_count=0,
            )
            mock_pipeline.filter.return_value = result
            mock_pipeline_class.return_value = mock_pipeline

            await _handle_filter(args)

        assert output_file.exists()
        captured = capsys.readouterr()
        assert "Filtered:" in captured.out

    @pytest.mark.asyncio
    async def test_handle_filter_autogenerated_keywords_empty_exits(
        self, sample_papers_json, tmp_path
    ):
        output_file = tmp_path / "filtered.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            keywords=None,
            exclude=None,
            authors=None,
            min_date=None,
            has_pdf=False,
            ai=False,
        )

        with patch(
            "src.ai.keyword_generator.KeywordGenerator.extract_keywords",
            new=AsyncMock(return_value=[]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await _handle_filter(args)

        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_handle_filter_with_min_date(self, sample_papers_json, tmp_path):
        """Test filter handler parses --min-date."""
        output_file = tmp_path / "filtered.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            keywords=["test"],
            exclude=None,
            authors=None,
            min_date="2024-01-01",
            has_pdf=False,
            ai=True,
        )

        with patch("src.filters.pipeline.FilterPipeline") as mock_pipeline_class:
            mock_pipeline = AsyncMock()
            result = FilterResult(
                papers=[],
                total_count=2,
                passed_count=0,
                rejected_count=2,
            )
            mock_pipeline.filter.return_value = result
            mock_pipeline_class.return_value = mock_pipeline

            await _handle_filter(args)

            # Verify min_date was parsed
            call_args = mock_pipeline.filter.call_args
            criteria = call_args[0][1]
            assert criteria.min_date == date(2024, 1, 1)

    @pytest.mark.asyncio
    async def test_handle_filter_with_all_criteria(self, sample_papers_json, tmp_path):
        """Test filter handler with multiple criteria."""
        output_file = tmp_path / "filtered.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            keywords=["machine"],
            exclude=["review"],
            authors=["Author"],
            min_date="2024-01-01",
            has_pdf=True,
            ai=True,
        )

        with patch("src.filters.pipeline.FilterPipeline") as mock_pipeline_class:
            mock_pipeline = AsyncMock()
            result = FilterResult(
                papers=[],
                total_count=2,
                passed_count=0,
                rejected_count=2,
            )
            mock_pipeline.filter.return_value = result
            mock_pipeline_class.return_value = mock_pipeline

            await _handle_filter(args)

            # Verify all criteria were set
            call_args = mock_pipeline.filter.call_args
            criteria = call_args[0][1]
            assert criteria.keywords == ["machine"]
            assert criteria.exclude_keywords == ["review"]
            assert criteria.authors == ["Author"]
            assert criteria.min_date == date(2024, 1, 1)
            assert criteria.has_pdf is True

    @pytest.mark.asyncio
    async def test_handle_filter_ai_without_key_skips(
        self, sample_papers_json, tmp_path, capsys
    ):
        """Test filter with --ai but no OPENAI_API_KEY skips AI."""
        output_file = tmp_path / "filtered.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            keywords=["test"],
            exclude=None,
            authors=None,
            min_date=None,
            has_pdf=False,
            ai=True,
        )

        with patch("src.client.cli.get_openai_config") as mock_config:
            mock_config.return_value = {"api_key": None}

            with patch(
                "src.filters.pipeline.FilterPipeline"
            ) as mock_pipeline_class:
                mock_pipeline = AsyncMock()
                result = FilterResult(
                    papers=[],
                    total_count=2,
                    passed_count=2,
                    rejected_count=0,
                )
                mock_pipeline.filter.return_value = result
                mock_pipeline_class.return_value = mock_pipeline

                await _handle_filter(args)

                # Verify llm_client was None (not initialized)
                call_args = mock_pipeline_class.call_args
                assert call_args.kwargs.get("llm_client") is None

        captured = capsys.readouterr()
        assert "OPENAI_API_KEY not set" in captured.err

    @pytest.mark.asyncio
    async def test_handle_filter_invalid_input_exits(self, tmp_path):
        """Test filter with missing input file exits."""
        args = argparse.Namespace(
            input="/missing/file.json",
            output="/tmp/out.json",
            keywords=None,
            exclude=None,
            authors=None,
            min_date=None,
            has_pdf=False,
            ai=False,
        )

        with pytest.raises(SystemExit) as exc_info:
            await _handle_filter(args)

        assert exc_info.value.code == 1


# -------------------- Tests: _handle_export --------------------


class TestHandleExport:
    """Tests for _handle_export handler."""

    @pytest.mark.asyncio
    async def test_handle_export_json_format(
        self, sample_papers_json, tmp_path, capsys
    ):
        """Test export handler with JSON format."""
        output_file = tmp_path / "export.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            format="json",
            output=str(output_file),
            include_metadata=False,
            collection=None,
        )

        with patch("src.adapters.json.JSONAdapter") as mock_adapter_class:
            mock_adapter = AsyncMock()
            mock_adapter_class.return_value = mock_adapter

            await _handle_export(args)

            # Verify adapter.export was called
            mock_adapter.export.assert_called_once()
            call_args = mock_adapter.export.call_args
            assert len(call_args[0][0]) == 2  # 2 papers
            assert call_args[0][1] == str(output_file)
            assert call_args.kwargs.get("include_metadata") is False

        captured = capsys.readouterr()
        assert "Exported 2 papers (json)" in captured.out

    @pytest.mark.asyncio
    async def test_handle_export_zotero_format(
        self, sample_papers_json, tmp_path, capsys
    ):
        """Test export handler with Zotero format."""
        args = argparse.Namespace(
            input=str(sample_papers_json),
            format="zotero",
            output="unused",  # Zotero doesn't use output path
            include_metadata=False,
            collection="ABCD1234",
        )

        with patch("src.client.cli.get_zotero_config") as mock_get_zotero_config:
            mock_get_zotero_config.return_value = {
                "library_id": "123",
                "api_key": "key",
                "library_type": "user",
                "target_collection": None,
            }
            with patch("src.adapters.zotero.ZoteroAdapter") as mock_adapter_class:
                mock_adapter = AsyncMock()
                mock_adapter.export.return_value = {
                    "success_count": 1,
                    "skipped_count": 1,
                    "failures": [],
                }
                mock_adapter_class.return_value = mock_adapter

                await _handle_export(args)

                # Verify adapter.export was called
                mock_adapter.export.assert_called_once()
                call_args = mock_adapter.export.call_args
                assert len(call_args[0][0]) == 2  # 2 papers
                assert call_args.kwargs.get("collection_id") == "ABCD1234"

        captured = capsys.readouterr()
        assert "Exported 2 papers (zotero)" in captured.out

    @pytest.mark.asyncio
    async def test_handle_export_zotero_uses_default_collection_from_config(
        self, sample_papers_json
    ):
        args = argparse.Namespace(
            input=str(sample_papers_json),
            format="zotero",
            output="unused",
            include_metadata=False,
            collection=None,
        )

        with patch("src.client.cli.get_zotero_config") as mock_get_zotero_config:
            mock_get_zotero_config.return_value = {
                "library_id": "123",
                "api_key": "key",
                "library_type": "user",
                "target_collection": "CFG12345",
            }
            with patch("src.adapters.zotero.ZoteroAdapter") as mock_adapter_class:
                mock_adapter = AsyncMock()
                mock_adapter.export.return_value = {
                    "success_count": 2,
                    "skipped_count": 0,
                    "failures": [],
                }
                mock_adapter_class.return_value = mock_adapter

                await _handle_export(args)

                call_args = mock_adapter.export.call_args
                assert call_args.kwargs.get("collection_id") == "CFG12345"

    @pytest.mark.asyncio
    async def test_handle_export_json_with_metadata(self, sample_papers_json, tmp_path):
        """Test export handler passes include_metadata flag."""
        output_file = tmp_path / "export.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            format="json",
            output=str(output_file),
            include_metadata=True,
            collection=None,
        )

        with patch("src.adapters.json.JSONAdapter") as mock_adapter_class:
            mock_adapter = AsyncMock()
            mock_adapter_class.return_value = mock_adapter

            await _handle_export(args)

            call_args = mock_adapter.export.call_args
            assert call_args.kwargs.get("include_metadata") is True

    @pytest.mark.asyncio
    async def test_handle_export_invalid_format_exits(
        self, sample_papers_json, tmp_path
    ):
        """Test export with invalid format exits."""
        args = argparse.Namespace(
            input=str(sample_papers_json),
            format="invalid",
            output="/tmp/out.json",
            include_metadata=False,
            collection=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            await _handle_export(args)

        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_handle_export_invalid_input_exits(self, tmp_path):
        """Test export with missing input file exits."""
        args = argparse.Namespace(
            input="/missing/file.json",
            format="json",
            output="/tmp/out.json",
            include_metadata=False,
            collection=None,
        )

        with pytest.raises(SystemExit) as exc_info:
            await _handle_export(args)

        assert exc_info.value.code == 1


# -------------------- Tests: _handle_enrich --------------------


class TestHandleEnrich:
    """Tests for _handle_enrich handler."""

    @pytest.mark.asyncio
    async def test_handle_enrich_crossref_source(
        self, sample_papers_json, sample_papers, tmp_path, capsys
    ):
        """Test enrich handler with Crossref source."""
        output_file = tmp_path / "enriched.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            source="crossref",
            concurrency=5,
        )

        with patch("src.sources.crossref.CrossrefClient") as mock_client_class:
            mock_client = AsyncMock()
            # Return modified paper to show enrichment
            mock_paper = sample_papers[0].model_copy()
            mock_paper.extra["enriched"] = True
            mock_client.enrich_paper.return_value = mock_paper
            mock_client_class.return_value = mock_client

            await _handle_enrich(args)

        assert output_file.exists()
        captured = capsys.readouterr()
        assert "Enriched" in captured.out

    @pytest.mark.asyncio
    async def test_handle_enrich_openalex_source(
        self, sample_papers_json, sample_papers, tmp_path
    ):
        """Test enrich handler with OpenAlex source."""
        output_file = tmp_path / "enriched.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            source="openalex",
            concurrency=5,
        )

        with patch("src.sources.openalex.OpenAlexClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.enrich_paper.return_value = sample_papers[0]
            mock_client_class.return_value = mock_client

            await _handle_enrich(args)

        assert output_file.exists()

    @pytest.mark.asyncio
    async def test_handle_enrich_all_sources(
        self, sample_papers_json, sample_papers, tmp_path
    ):
        """Test enrich handler with both sources."""
        output_file = tmp_path / "enriched.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            source="all",
            concurrency=5,
        )

        with patch("src.sources.crossref.CrossrefClient") as mock_crossref_class:
            with patch(
                "src.sources.openalex.OpenAlexClient"
            ) as mock_openalex_class:
                mock_crossref = AsyncMock()
                mock_openalex = AsyncMock()

                mock_crossref.enrich_paper.return_value = sample_papers[0]
                mock_openalex.enrich_paper.return_value = sample_papers[0]

                mock_crossref_class.return_value = mock_crossref
                mock_openalex_class.return_value = mock_openalex

                await _handle_enrich(args)

        assert output_file.exists()

    @pytest.mark.asyncio
    async def test_handle_enrich_respects_concurrency(
        self, sample_papers_json, sample_papers, tmp_path
    ):
        """Test enrich handler respects concurrency limit."""
        output_file = tmp_path / "enriched.json"

        args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(output_file),
            source="crossref",
            concurrency=2,
        )

        with patch("src.sources.crossref.CrossrefClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.enrich_paper.return_value = sample_papers[0]
            mock_client_class.return_value = mock_client

            # Create a semaphore to verify concurrency
            original_semaphore = asyncio.Semaphore

            with patch("asyncio.Semaphore", wraps=original_semaphore) as mock_sem:
                await _handle_enrich(args)

                # Verify semaphore was created with concurrency value
                mock_sem.assert_called_once_with(2)

    @pytest.mark.asyncio
    async def test_handle_enrich_invalid_input_exits(self, tmp_path):
        """Test enrich with missing input file exits."""
        args = argparse.Namespace(
            input="/missing/file.json",
            output="/tmp/out.json",
            source="all",
            concurrency=5,
        )

        with pytest.raises(SystemExit) as exc_info:
            await _handle_enrich(args)

        assert exc_info.value.code == 1


# -------------------- Tests: main --------------------


class TestMain:
    """Tests for main CLI entry point."""

    @staticmethod
    def _close_coro(coro):
        try:
            coro.close()
        except Exception:
            pass

    def test_main_no_args_runs_server(self):
        """Test main with no arguments runs server."""
        with patch("sys.argv", ["feedder-mcp"]):
            with patch("asyncio.run", side_effect=self._close_coro) as mock_run:
                main()
                mock_run.assert_called_once()

    def test_main_help_flag(self, capsys):
        """Test main with --help flag."""
        with patch("sys.argv", ["feedder-mcp", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 0

        captured = capsys.readouterr()
        assert "usage:" in captured.out

    def test_main_unknown_command_exits(self, capsys):
        """Test main with unknown command exits."""
        with patch("sys.argv", ["feedder-mcp", "unknown"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

            # argparse exits with code 2 for invalid choice
            assert exc_info.value.code != 0

    def test_main_calls_handler_for_valid_command(self):
        """Test main dispatches to correct handler."""
        with patch("sys.argv", ["feedder-mcp", "fetch", "--output", "out.json"]):
            with patch("src.client.cli._handle_fetch") as mock_handler:
                mock_handler.return_value = None

                with patch("asyncio.run", side_effect=self._close_coro) as mock_run:
                    main()

                    # Verify handler was passed to asyncio.run
                    mock_run.assert_called_once()

    def test_main_keyboard_interrupt_exits(self, capsys):
        """Test main handles KeyboardInterrupt."""
        with patch("sys.argv", ["feedder-mcp", "fetch", "--output", "out.json"]):
            def _raise_interrupt(coro):
                self._close_coro(coro)
                raise KeyboardInterrupt()

            with patch("asyncio.run", side_effect=_raise_interrupt):
                with pytest.raises(SystemExit) as exc_info:
                    main()

                assert exc_info.value.code == 130

        captured = capsys.readouterr()
        assert "Interrupted" in captured.err

    def test_main_generic_exception_exits(self, capsys):
        """Test main handles generic exceptions."""
        with patch("sys.argv", ["feedder-mcp", "fetch", "--output", "out.json"]):
            def _raise_error(coro):
                self._close_coro(coro)
                raise ValueError("Test error")

            with patch("asyncio.run", side_effect=_raise_error):
                with pytest.raises(SystemExit) as exc_info:
                    main()

                assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "Error:" in captured.err


# -------------------- Integration-style Tests --------------------


class TestIntegration:
    """Integration-style tests combining multiple components."""

    @pytest.mark.asyncio
    async def test_fetch_and_save_workflow(self, tmp_path, sample_papers):
        """Test complete fetch and save workflow."""
        output_file = tmp_path / "fetched.json"

        args = argparse.Namespace(
            source="rss",
            opml=None,
            limit=None,
            since=None,
            output=str(output_file),
        )

        with patch("src.sources.rss.RSSSource") as mock_rss_class:
            mock_source = AsyncMock()
            mock_source.fetch_papers.return_value = sample_papers
            mock_rss_class.return_value = mock_source

            with patch("src.client.cli.get_rss_config") as mock_config:
                mock_config.return_value = {"opml_path": "feeds/test.opml"}

                await _handle_fetch(args)

        # Verify file was created and can be loaded back
        loaded_papers = _load_papers(str(output_file))
        assert len(loaded_papers) == 2
        assert loaded_papers[0].title == "Test Paper 1"

    @pytest.mark.asyncio
    async def test_filter_and_export_workflow(self, sample_papers_json, tmp_path):
        """Test complete filter and export workflow."""
        filtered_file = tmp_path / "filtered.json"

        filter_args = argparse.Namespace(
            input=str(sample_papers_json),
            output=str(filtered_file),
            keywords=["machine"],
            exclude=None,
            authors=None,
            min_date=None,
            has_pdf=False,
            ai=False,
        )

        with patch("src.filters.pipeline.FilterPipeline") as mock_pipeline_class:
            mock_pipeline = AsyncMock()
            result = FilterResult(
                papers=[],
                total_count=2,
                passed_count=0,
                rejected_count=2,
            )
            mock_pipeline.filter.return_value = result
            mock_pipeline_class.return_value = mock_pipeline

            await _handle_filter(filter_args)

        # Now export
        export_args = argparse.Namespace(
            input=str(filtered_file),
            format="json",
            output=str(tmp_path / "export.json"),
            include_metadata=False,
            collection=None,
        )

        with patch("src.adapters.json.JSONAdapter") as mock_adapter_class:
            mock_adapter = AsyncMock()
            mock_adapter_class.return_value = mock_adapter

            await _handle_export(export_args)

