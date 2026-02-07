"""Unit tests for AI modules: keyword_generator.py and ai_filter.py.

Tests cover:
- KeywordGenerator: keyword parsing, text normalization, matching strategies, filtering
- AIFilterStage: filtering logic, output parsing, index validation
"""

import json
from unittest.mock import MagicMock

import pytest

from paper_feed.filters.ai_filter import AIFilterStage
from paper_feed.ai.keyword_generator import KeywordGenerator
from paper_feed.core.models import FilterCriteria, PaperItem


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sample_papers() -> list[PaperItem]:
    """Create sample papers for testing."""
    return [
        PaperItem(
            title="Zinc-air battery electrode materials",
            abstract="A comprehensive study of Zn anodes in aqueous electrolytes",
            source="arXiv",
            source_type="rss",
            authors=["John Smith", "Jane Doe"],
        ),
        PaperItem(
            title="Lithium-ion battery performance optimization",
            abstract="Novel cathode materials for Li-ion battery systems",
            source="Nature",
            source_type="rss",
            authors=["Alice Brown"],
        ),
        PaperItem(
            title="Machine learning for protein folding",
            abstract="Deep learning approaches to predict 3D protein structures",
            source="bioRxiv",
            source_type="rss",
            authors=["Bob Wilson"],
        ),
        PaperItem(
            title="Operando XAS of transition metal oxides",
            abstract="In-situ synchrotron X-ray absorption spectroscopy",
            source="Science",
            source_type="rss",
            authors=["Carol Davis"],
        ),
        PaperItem(
            title="Review of battery technologies",
            abstract="A survey of recent battery developments",
            source="arXiv",
            source_type="rss",
        ),
    ]


@pytest.fixture
def mock_openai_client() -> MagicMock:
    """Create a mock OpenAI client."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"keywords": ["zinc", "battery"]}'
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


@pytest.fixture
def mock_config(monkeypatch):
    """Mock configuration functions."""

    def mock_get_openai_config():
        return {
            "api_key": "test-api-key",
            "model": "gpt-4o-mini",
            "base_url": None,
        }

    def mock_get_research_prompt():
        return "Interested in battery materials and electrochemistry"

    monkeypatch.setattr(
        "paper_feed.ai.keyword_generator.get_openai_config",
        mock_get_openai_config,
    )
    monkeypatch.setattr(
        "paper_feed.ai.keyword_generator.get_research_prompt",
        mock_get_research_prompt,
    )
    monkeypatch.setattr(
        "paper_feed.filters.ai_filter.get_openai_config",
        mock_get_openai_config,
    )
    monkeypatch.setattr(
        "paper_feed.filters.ai_filter.get_research_prompt",
        mock_get_research_prompt,
    )


# ============================================================================
# KeywordGenerator Tests
# ============================================================================


class TestKeywordGeneratorParsing:
    """Tests for _parse_keywords_json() with different strategies."""

    def test_parse_keywords_strategy_1_direct_json(self):
        """Strategy 1: Direct JSON parse with keywords field."""
        kg = KeywordGenerator(api_key="test")
        content = '{"keywords": ["zinc", "battery", "electrode"]}'
        result = kg._parse_keywords_json(content)
        assert result == ["zinc", "battery", "electrode"]

    def test_parse_keywords_strategy_2_markdown_code_block(self):
        """Strategy 2: Extract from markdown code block."""
        kg = KeywordGenerator(api_key="test")
        content = """
        Some explanation text here
        ```json
        {"keywords": ["operando", "xas", "synchrotron"]}
        ```
        More explanation
        """
        result = kg._parse_keywords_json(content)
        assert result == ["operando", "xas", "synchrotron"]

    def test_parse_keywords_strategy_3_array_extraction(self):
        """Strategy 3: Extract JSON array from content."""
        kg = KeywordGenerator(api_key="test")
        content = 'Some text ["keyword1", "keyword2", "keyword3"] more text'
        result = kg._parse_keywords_json(content)
        assert result == ["keyword1", "keyword2", "keyword3"]

    def test_parse_keywords_strategy_4_quoted_strings_fallback(self):
        """Strategy 4: Last resort - extract quoted strings."""
        kg = KeywordGenerator(api_key="test")
        content = 'The keywords are "lithium", "manganese", and "oxygen"'
        result = kg._parse_keywords_json(content)
        assert "lithium" in result
        assert "manganese" in result
        assert "oxygen" in result

    def test_parse_keywords_empty_input(self):
        """Empty or invalid input returns empty list."""
        kg = KeywordGenerator(api_key="test")
        assert kg._parse_keywords_json("") == []
        assert kg._parse_keywords_json("no json here") == []

    def test_parse_keywords_with_empty_strings_filtered(self):
        """Empty keywords are filtered out."""
        kg = KeywordGenerator(api_key="test")
        content = '{"keywords": ["zinc", "", "battery", null]}'
        result = kg._parse_keywords_json(content)
        assert "" not in result
        assert "zinc" in result
        assert "battery" in result


class TestKeywordGeneratorNormalization:
    """Tests for _normalize_text() method."""

    def test_normalize_lowercases(self):
        """Normalize converts to lowercase."""
        kg = KeywordGenerator(api_key="test")
        assert kg._normalize_text("ZINC") == "zinc"
        assert kg._normalize_text("LithiuM") == "lithium"

    def test_normalize_replaces_hyphens_underscores(self):
        """Normalize replaces hyphens and underscores with spaces."""
        kg = KeywordGenerator(api_key="test")
        assert kg._normalize_text("zinc-air") == "zinc air"
        assert kg._normalize_text("li_ion") == "li ion"
        assert kg._normalize_text("in-situ") == "in situ"

    def test_normalize_removes_punctuation(self):
        """Normalize removes special punctuation."""
        kg = KeywordGenerator(api_key="test")
        assert (
            kg._normalize_text("battery, electrode: material")
            == "battery electrode material"
        )
        assert kg._normalize_text("MnO₂") == "mno₂"

    def test_normalize_collapses_whitespace(self):
        """Normalize collapses multiple spaces."""
        kg = KeywordGenerator(api_key="test")
        assert kg._normalize_text("zinc  air   battery") == "zinc air battery"


class TestKeywordGeneratorStemming:
    """Tests for _get_word_stem() method."""

    def test_stem_plurals_ies_ending(self):
        """Stem converts 'ies' to 'y'."""
        kg = KeywordGenerator(api_key="test")
        assert kg._get_word_stem("batteries") == "battery"
        assert kg._get_word_stem("properties") == "property"

    def test_stem_plurals_es_ending(self):
        """Stem removes 'es' from plurals."""
        kg = KeywordGenerator(api_key="test")
        assert kg._get_word_stem("glasses") == "glass"
        assert kg._get_word_stem("boxes") == "box"

    def test_stem_plurals_s_ending(self):
        """Stem removes trailing 's'."""
        kg = KeywordGenerator(api_key="test")
        assert kg._get_word_stem("materials") == "material"
        assert kg._get_word_stem("electrodes") == "electrod"

    def test_stem_past_tense_ed(self):
        """Stem removes 'ed' suffix."""
        kg = KeywordGenerator(api_key="test")
        assert kg._get_word_stem("computed") == "comput"
        assert kg._get_word_stem("studied") == "studi"

    def test_stem_present_participle_ing(self):
        """Stem removes 'ing' suffix."""
        kg = KeywordGenerator(api_key="test")
        assert kg._get_word_stem("running") == "runn"
        assert kg._get_word_stem("computing") == "comput"

    def test_stem_no_suffix_unchanged(self):
        """Stem returns word unchanged if no suffix matches."""
        kg = KeywordGenerator(api_key="test")
        assert kg._get_word_stem("zinc") == "zinc"
        assert kg._get_word_stem("battery") == "battery"


class TestKeywordGeneratorMatching:
    """Tests for _matches_keyword() with 5 strategies."""

    def test_match_strategy_1_exact_substring(self):
        """Strategy 1: Exact substring after normalization."""
        kg = KeywordGenerator(api_key="test")
        text = "Zinc-air battery electrode"
        assert kg._matches_keyword(text, "zinc") is True
        assert kg._matches_keyword(text, "battery") is True
        assert kg._matches_keyword(text, "zinc air") is True

    def test_match_strategy_2_all_words_present(self):
        """Strategy 2: All keyword words in text."""
        kg = KeywordGenerator(api_key="test")
        text = "Novel Lithium-ion battery cathode"
        assert kg._matches_keyword(text, "lithium battery") is True
        assert kg._matches_keyword(text, "battery cathode") is True

    def test_match_strategy_3_stem_based(self):
        """Strategy 3: Stem-based matching."""
        kg = KeywordGenerator(api_key="test")
        text = "Materials and batteries for energy storage"
        assert kg._matches_keyword(text, "material") is True  # material vs materials
        assert kg._matches_keyword(text, "battery") is True

    def test_match_strategy_4_chemical_synonyms(self):
        """Strategy 4: Chemical synonym matching."""
        kg = KeywordGenerator(api_key="test")
        text = "Zn anode in aqueous electrolyte"
        assert kg._matches_keyword(text, "zinc") is True  # zinc ↔ zn

        text = "Li-ion battery system"
        assert kg._matches_keyword(text, "lithium") is True  # lithium ↔ li

    def test_match_strategy_5_core_terms(self):
        """Strategy 5: Core term matching (operando, synchrotron, etc)."""
        kg = KeywordGenerator(api_key="test")
        text = "Operando XAS analysis of transition metals"
        assert kg._matches_keyword(text, "operando") is True

        text = "In-situ synchrotron XRD study"
        assert kg._matches_keyword(text, "synchrotron") is True
        assert kg._matches_keyword(text, "xrd") is True

    def test_match_case_insensitive(self):
        """All matching is case-insensitive."""
        kg = KeywordGenerator(api_key="test")
        text = "BATTERY ELECTRODE MATERIALS"
        assert kg._matches_keyword(text, "battery") is True
        assert kg._matches_keyword(text, "ZINC") is False

    def test_match_no_match_returns_false(self):
        """No match returns False."""
        kg = KeywordGenerator(api_key="test")
        text = "Protein folding study"
        assert kg._matches_keyword(text, "battery") is False
        assert kg._matches_keyword(text, "zinc") is False


class TestKeywordGeneratorFiltering:
    """Tests for filter_items() method."""

    def test_filter_items_with_keywords(self, sample_papers):
        """Filter papers by keywords."""
        kg = KeywordGenerator(api_key="test")
        keywords = ["zinc", "battery"]
        relevant, irrelevant = kg.filter_items(sample_papers, keywords)

        assert len(relevant) > 0
        assert len(irrelevant) > 0
        assert len(relevant) + len(irrelevant) == len(sample_papers)
        # First paper should be relevant (title contains zinc, battery)
        assert sample_papers[0] in relevant

    def test_filter_items_no_keywords_raises_error(self, sample_papers):
        """Filtering without keywords raises ValueError."""
        kg = KeywordGenerator(api_key="test")
        with pytest.raises(ValueError, match="No keywords available"):
            kg.filter_items(sample_papers)

    def test_filter_items_cached_keywords(self, sample_papers, monkeypatch):
        """Filter uses cached keywords if not provided."""
        kg = KeywordGenerator(api_key="test")
        kg._keywords = ["operando", "synchrotron"]

        relevant, irrelevant = kg.filter_items(sample_papers)
        assert sample_papers[3] in relevant  # operando, synchrotron paper


# ============================================================================
# AIFilterStage Tests
# ============================================================================


class TestAIFilterStageApplicability:
    """Tests for is_applicable() method."""

    def test_is_applicable_with_client(self, mock_config):
        """is_applicable returns True when client is set."""
        client = MagicMock()
        stage = AIFilterStage(openai_client=client)
        criteria = FilterCriteria()
        assert stage.is_applicable(criteria) is True

    def test_is_applicable_without_client(self, mock_config, monkeypatch):
        """is_applicable returns False when client is None."""
        monkeypatch.setattr(
            "paper_feed.filters.ai_filter.get_openai_config",
            lambda: {"api_key": None, "model": "gpt-4o-mini", "base_url": None},
        )
        stage = AIFilterStage(openai_client=None)
        criteria = FilterCriteria()
        assert stage.is_applicable(criteria) is False


class TestAIFilterStageBuildPapersText:
    """Tests for _build_papers_text() method."""

    def test_build_papers_text_format(self, sample_papers, mock_config):
        """Build papers text with correct format."""
        stage = AIFilterStage(openai_client=MagicMock())
        text = stage._build_papers_text(sample_papers[:2])

        assert "[0]" in text
        assert "[1]" in text
        assert sample_papers[0].title in text
        assert sample_papers[1].title in text

    def test_build_papers_text_truncates_abstract(self, mock_config):
        """Build papers text truncates long abstracts."""
        stage = AIFilterStage(openai_client=MagicMock())
        long_abstract = "x" * 1000
        papers = [
            PaperItem(
                title="Test Paper",
                abstract=long_abstract,
                source="Test",
                source_type="rss",
            )
        ]
        text = stage._build_papers_text(papers)
        assert len(text) < len(long_abstract) + 100  # With some margin
        assert "..." in text

    def test_build_papers_text_empty_abstract(self, mock_config):
        """Build papers text handles empty abstracts."""
        stage = AIFilterStage(openai_client=MagicMock())
        papers = [
            PaperItem(
                title="Title Only",
                abstract="",
                source="Test",
                source_type="rss",
            )
        ]
        text = stage._build_papers_text(papers)
        assert "Title Only" in text


class TestAIFilterStageParseOutput:
    """Tests for _parse_filter_output() method."""

    def test_parse_output_strategy_1_direct_json(self, mock_config):
        """Strategy 1: Direct JSON parse."""
        stage = AIFilterStage(openai_client=MagicMock())
        output = '{"relevant": [0, 2, 3]}'
        result = stage._parse_filter_output(output, batch_size=5)
        assert result == {0, 2, 3}

    def test_parse_output_strategy_2_markdown_code_block(self, mock_config):
        """Strategy 2: Extract from markdown code block."""
        stage = AIFilterStage(openai_client=MagicMock())
        output = """
        Here are the relevant papers:
        ```json
        {"relevant": [1, 4]}
        ```
        """
        result = stage._parse_filter_output(output, batch_size=5)
        assert result == {1, 4}

    def test_parse_output_strategy_3_json_object_anywhere(self, mock_config):
        """Strategy 3: Find JSON object anywhere in output."""
        stage = AIFilterStage(openai_client=MagicMock())
        output = 'Some text before {"relevant": [0, 1, 2]} some text after'
        result = stage._parse_filter_output(output, batch_size=5)
        assert result == {0, 1, 2}

    def test_parse_output_invalid_returns_empty(self, mock_config):
        """Invalid output returns empty set."""
        stage = AIFilterStage(openai_client=MagicMock())
        output = "This is not valid JSON at all"
        result = stage._parse_filter_output(output, batch_size=5)
        assert result == set()

    def test_parse_output_empty_relevant(self, mock_config):
        """Empty relevant array is valid."""
        stage = AIFilterStage(openai_client=MagicMock())
        output = '{"relevant": []}'
        result = stage._parse_filter_output(output, batch_size=5)
        assert result == set()


class TestAIFilterStageValidateIndices:
    """Tests for _validate_indices() method."""

    def test_validate_indices_in_range(self, mock_config):
        """Valid indices within range are accepted."""
        stage = AIFilterStage(openai_client=MagicMock())
        indices = [0, 1, 2, 3, 4]
        result = stage._validate_indices(indices, batch_size=5)
        assert result == {0, 1, 2, 3, 4}

    def test_validate_indices_filters_out_of_range(self, mock_config):
        """Out-of-range indices are filtered."""
        stage = AIFilterStage(openai_client=MagicMock())
        indices = [0, 5, 10, 2]  # 5 and 10 out of range
        result = stage._validate_indices(indices, batch_size=5)
        assert result == {0, 2}

    def test_validate_indices_filters_non_integer(self, mock_config):
        """Non-integer values are filtered."""
        stage = AIFilterStage(openai_client=MagicMock())
        indices = [0, "invalid", 2, 3.5, None]
        result = stage._validate_indices(indices, batch_size=5)
        assert result == {0, 2, 3}

    def test_validate_indices_negative(self, mock_config):
        """Negative indices are rejected."""
        stage = AIFilterStage(openai_client=MagicMock())
        indices = [-1, 0, 1, 2]
        result = stage._validate_indices(indices, batch_size=5)
        assert result == {0, 1, 2}


class TestAIFilterStageFilter:
    """Tests for filter() method."""

    async def test_filter_with_mocked_client(self, sample_papers, mock_config):
        """Filter with mocked OpenAI client."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"relevant": [0, 2]}'
        mock_client.chat.completions.create.return_value = mock_response

        stage = AIFilterStage(openai_client=mock_client)
        filtered, messages = await stage.filter(sample_papers, FilterCriteria())

        assert len(filtered) == 2
        assert len(messages) > 0
        assert sample_papers[0] in filtered
        assert sample_papers[2] in filtered

    async def test_filter_without_client(self, sample_papers, mock_config, monkeypatch):
        """Filter without client returns all papers."""
        monkeypatch.setattr(
            "paper_feed.filters.ai_filter.get_openai_config",
            lambda: {"api_key": None, "model": "gpt-4o-mini", "base_url": None},
        )
        stage = AIFilterStage(openai_client=None)
        filtered, messages = await stage.filter(sample_papers, FilterCriteria())

        assert len(filtered) == len(sample_papers)
        assert any("skipped" in msg.lower() for msg in messages)

    async def test_filter_without_research_prompt(
        self, sample_papers, mock_config, monkeypatch
    ):
        """Filter without research prompt returns all papers."""
        monkeypatch.setattr(
            "paper_feed.filters.ai_filter.get_research_prompt",
            lambda: None,
        )

        mock_client = MagicMock()
        stage = AIFilterStage(openai_client=mock_client)
        filtered, messages = await stage.filter(sample_papers, FilterCriteria())

        assert len(filtered) == len(sample_papers)
        assert any("research prompt" in msg.lower() for msg in messages)

    async def test_filter_empty_papers(self, mock_config):
        """Filter with empty papers list."""
        mock_client = MagicMock()
        stage = AIFilterStage(openai_client=mock_client)
        filtered, messages = await stage.filter([], FilterCriteria())

        assert len(filtered) == 0

    async def test_filter_batch_processing(self, mock_config):
        """Filter processes large paper list in batches."""
        # Create 100 papers
        papers = [
            PaperItem(
                title=f"Paper {i}",
                abstract=f"Abstract for paper {i}",
                source="Test",
                source_type="rss",
            )
            for i in range(100)
        ]

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        # Mock response for first batch
        mock_response.choices[0].message.content = '{"relevant": [0, 1]}'
        mock_client.chat.completions.create.return_value = mock_response

        stage = AIFilterStage(openai_client=mock_client)
        filtered, messages = await stage.filter(papers, FilterCriteria())

        # Should call API multiple times (100 / BATCH_SIZE)
        assert mock_client.chat.completions.create.call_count >= 1

    async def test_filter_error_handling_fail_open(self, sample_papers, mock_config):
        """On API error, filter treats all papers as relevant."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")

        stage = AIFilterStage(openai_client=mock_client)
        filtered, messages = await stage.filter(sample_papers, FilterCriteria())

        # Should return all papers on error (fail-open)
        assert len(filtered) == len(sample_papers)


class TestKeywordGeneratorExtractKeywords:
    """Tests for extract_keywords() method."""

    async def test_extract_keywords_with_prompt(
        self, tmp_path, mock_config, monkeypatch
    ):
        """Extract keywords from provided prompt."""
        # Mock the cache file location
        monkeypatch.setattr(
            "paper_feed.ai.keyword_generator.KEYWORDS_CACHE_FILE",
            tmp_path / "cache" / "keywords.json",
        )

        kg = KeywordGenerator(api_key="test")
        kg._generate_candidates = MagicMock(  # type: ignore[assignment]
            return_value=["zinc", "battery", "electrode"]
        )
        kg._select_best_keywords = MagicMock(return_value=["zinc", "battery"])  # type: ignore[assignment]

        result = await kg.extract_keywords("Research on batteries")
        assert "zinc" in result or "battery" in result

    async def test_extract_keywords_no_prompt_raises_error(
        self, mock_config, monkeypatch
    ):
        """Extract without prompt raises ValueError."""
        monkeypatch.setattr(
            "paper_feed.ai.keyword_generator.get_research_prompt",
            lambda: None,
        )

        kg = KeywordGenerator(api_key="test")
        with pytest.raises(ValueError, match="No research prompt"):
            await kg.extract_keywords()

    async def test_extract_keywords_uses_cache(
        self, tmp_path, mock_config, monkeypatch
    ):
        """Extract keywords uses cached results."""
        cache_file = tmp_path / "cache" / "keywords.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        import hashlib

        prompt_hash = hashlib.sha256("Test prompt".encode("utf-8")).hexdigest()
        cache_file.write_text(
            json.dumps({"hash": prompt_hash, "keywords": ["cached1", "cached2"]})
        )

        monkeypatch.setattr(
            "paper_feed.ai.keyword_generator.KEYWORDS_CACHE_FILE",
            cache_file,
        )

        kg = KeywordGenerator(api_key="test")
        kg._generate_candidates = MagicMock()  # type: ignore[assignment]

        result = await kg.extract_keywords("Test prompt")
        assert result == ["cached1", "cached2"]
        # Should not call API if cache hit
        kg._generate_candidates.assert_not_called()  # type: ignore[union-attr]
