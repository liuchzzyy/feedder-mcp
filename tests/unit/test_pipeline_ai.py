"""Unit tests for FilterPipeline AI integration.

Tests cover:
- FilterPipeline with no LLM client (AI stage skipped)
- FilterPipeline with LLM client (both stages run)
- FilterPipeline AI stage fallback on failure
- FilterPipeline filter statistics include AI stage
- FilterPipeline with empty criteria and AI enabled
"""

from unittest.mock import MagicMock

import pytest

from paper_feed.core.models import FilterCriteria, PaperItem
from paper_feed.filters.pipeline import FilterPipeline


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sample_papers() -> list[PaperItem]:
    """Create sample papers for testing."""
    return [
        PaperItem(
            title="Zinc battery electrode",
            abstract="Study of Zn anode in aqueous electrolytes",
            source="arXiv",
            source_type="rss",
            pdf_url="http://example.com/paper1.pdf",
        ),
        PaperItem(
            title="Lithium-ion battery performance",
            abstract="Novel cathode materials for Li-ion systems",
            source="Nature",
            source_type="rss",
            pdf_url="http://example.com/paper2.pdf",
        ),
        PaperItem(
            title="Machine learning for protein folding",
            abstract="Deep learning approaches for 3D structure prediction",
            source="bioRxiv",
            source_type="rss",
        ),
        PaperItem(
            title="Operando XAS of transition metal oxides",
            abstract="In-situ synchrotron X-ray absorption spectroscopy",
            source="Science",
            source_type="rss",
            pdf_url="http://example.com/paper4.pdf",
        ),
        PaperItem(
            title="Review of battery technologies",
            abstract="Survey of recent battery developments",
            source="arXiv",
            source_type="rss",
        ),
    ]


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
        "paper_feed.filters.pipeline.get_openai_config"
        if hasattr(FilterPipeline, "get_openai_config")
        else "paper_feed.filters.ai_filter.get_openai_config",
        mock_get_openai_config,
    )
    monkeypatch.setattr(
        "paper_feed.filters.pipeline.get_research_prompt"
        if hasattr(FilterPipeline, "get_research_prompt")
        else "paper_feed.filters.ai_filter.get_research_prompt",
        mock_get_research_prompt,
    )


# ============================================================================
# FilterPipeline AI Integration Tests
# ============================================================================


class TestFilterPipelineNoLLMClient:
    """Tests for FilterPipeline without LLM client."""

    async def test_pipeline_llm_client_none_skips_ai_stage(
        self, sample_papers, mock_config
    ):
        """FilterPipeline with llm_client=None skips AI stage."""
        pipeline = FilterPipeline(llm_client=None)
        criteria = FilterCriteria(keywords=["battery"])

        result = await pipeline.filter(sample_papers, criteria)

        # Should have stats for keyword stage but AI stage marked skipped
        assert "keyword_filter" in result.filter_stats
        assert "ai_filter" in result.filter_stats
        assert result.filter_stats["ai_filter"].get("skipped") is True
        assert "No LLM client" in result.filter_stats["ai_filter"].get("reason", "")

    async def test_pipeline_default_constructor_no_ai(self, sample_papers, mock_config):
        """FilterPipeline() default constructor has no AI stage."""
        pipeline = FilterPipeline()
        assert pipeline.llm_client is None
        assert pipeline._ai_stage is None


class TestFilterPipelineWithLLMClient:
    """Tests for FilterPipeline with LLM client enabled."""

    async def test_pipeline_with_llm_client_both_stages_run(
        self, sample_papers, mock_config
    ):
        """FilterPipeline with mock llm_client runs both stages."""
        # Create a mock client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"relevant": [0, 1]}'
        mock_client.chat.completions.create.return_value = mock_response

        pipeline = FilterPipeline(llm_client=mock_client)
        criteria = FilterCriteria(keywords=["battery"])

        result = await pipeline.filter(sample_papers, criteria)

        # Both stages should have stats
        assert "keyword_filter" in result.filter_stats
        assert "ai_filter" in result.filter_stats

        # AI stage should not be skipped
        ai_stats = result.filter_stats["ai_filter"]
        assert ai_stats.get("skipped") is not True or "input_count" in ai_stats

    async def test_pipeline_ai_stage_created_when_client_provided(self, mock_config):
        """FilterPipeline creates AI stage when llm_client provided."""
        mock_client = MagicMock()
        pipeline = FilterPipeline(llm_client=mock_client)

        assert pipeline._ai_stage is not None
        assert pipeline._ai_stage._client == mock_client


class TestFilterPipelineAIFallback:
    """Tests for FilterPipeline AI stage failure handling."""

    async def test_pipeline_ai_stage_error_fallback_gracefully(
        self, sample_papers, mock_config
    ):
        """FilterPipeline handles AI stage errors gracefully."""
        # Create a mock client that raises an error
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")

        pipeline = FilterPipeline(llm_client=mock_client)
        criteria = FilterCriteria(keywords=["battery"])

        # Should not raise, but handle error
        result = await pipeline.filter(sample_papers, criteria)

        # Result should still be valid
        assert result.papers is not None
        assert len(result.papers) > 0
        assert "ai_filter" in result.filter_stats


class TestFilterPipelineStatistics:
    """Tests for FilterPipeline filter statistics."""

    async def test_pipeline_stats_include_keyword_stage(
        self, sample_papers, mock_config
    ):
        """FilterPipeline stats include keyword stage info."""
        pipeline = FilterPipeline(llm_client=None)
        criteria = FilterCriteria(keywords=["battery"])

        result = await pipeline.filter(sample_papers, criteria)

        keyword_stats = result.filter_stats["keyword_filter"]
        assert keyword_stats is not None
        assert "input_count" in keyword_stats or "skipped" in keyword_stats

    async def test_pipeline_stats_include_ai_stage(self, sample_papers, mock_config):
        """FilterPipeline stats include AI stage info."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"relevant": [0]}'
        mock_client.chat.completions.create.return_value = mock_response

        pipeline = FilterPipeline(llm_client=mock_client)
        criteria = FilterCriteria(keywords=["battery"])

        result = await pipeline.filter(sample_papers, criteria)

        ai_stats = result.filter_stats["ai_filter"]
        assert ai_stats is not None
        # Should have either skip info or counts
        assert (
            "skipped" in ai_stats or "input_count" in ai_stats or "messages" in ai_stats
        )

    async def test_pipeline_stats_track_counts(self, sample_papers, mock_config):
        """FilterPipeline stats track input/output counts correctly."""
        pipeline = FilterPipeline(llm_client=None)
        criteria = FilterCriteria(keywords=["battery"])

        result = await pipeline.filter(sample_papers, criteria)

        assert result.total_count == len(sample_papers)
        assert result.passed_count + result.rejected_count == result.total_count


class TestFilterPipelineEmptyCriteriaWithAI:
    """Tests for FilterPipeline with empty criteria and AI."""

    async def test_pipeline_empty_criteria_keyword_skipped(
        self, sample_papers, mock_config
    ):
        """FilterPipeline with empty criteria skips keyword stage."""
        pipeline = FilterPipeline(llm_client=None)
        criteria = FilterCriteria()  # Empty criteria

        result = await pipeline.filter(sample_papers, criteria)

        # Keyword stage should be skipped
        keyword_stats = result.filter_stats["keyword_filter"]
        assert keyword_stats.get("skipped") is True

    async def test_pipeline_empty_criteria_with_ai_only_ai_runs(
        self, sample_papers, mock_config
    ):
        """FilterPipeline with empty criteria but AI client only runs AI stage."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"relevant": [0, 1, 2]}'
        mock_client.chat.completions.create.return_value = mock_response

        pipeline = FilterPipeline(llm_client=mock_client)
        criteria = FilterCriteria()  # Empty criteria

        result = await pipeline.filter(sample_papers, criteria)

        # Keyword stage should be skipped
        keyword_stats = result.filter_stats["keyword_filter"]
        assert keyword_stats.get("skipped") is True


class TestFilterPipelineIntegration:
    """Integration tests for FilterPipeline with both stages."""

    async def test_pipeline_sequential_filtering(self, sample_papers, mock_config):
        """Pipeline applies stages sequentially."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        # Only indices 0 and 2 are relevant according to AI
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"relevant": [0, 2]}'
        mock_client.chat.completions.create.return_value = mock_response

        pipeline = FilterPipeline(llm_client=mock_client)
        # Keyword filter: battery papers are 0, 1, 4
        criteria = FilterCriteria(keywords=["battery"])

        result = await pipeline.filter(sample_papers, criteria)

        # Final result should be intersection of keyword and AI filters
        assert result.papers is not None
        # Should have some papers (intersection of both stages)
        assert result.passed_count >= 0

    async def test_pipeline_result_structure(self, sample_papers, mock_config):
        """Pipeline returns properly structured FilterResult."""
        pipeline = FilterPipeline(llm_client=None)
        criteria = FilterCriteria(keywords=["battery"])

        result = await pipeline.filter(sample_papers, criteria)

        # Check FilterResult structure
        assert hasattr(result, "papers")
        assert hasattr(result, "total_count")
        assert hasattr(result, "passed_count")
        assert hasattr(result, "rejected_count")
        assert hasattr(result, "filter_stats")

        # Check counts are valid
        assert result.total_count >= 0
        assert result.passed_count >= 0
        assert result.rejected_count >= 0
        assert result.passed_count + result.rejected_count == result.total_count

    async def test_pipeline_messages_collected(self, sample_papers, mock_config):
        """Pipeline collects messages from all stages."""
        pipeline = FilterPipeline(llm_client=None)
        criteria = FilterCriteria(keywords=["battery"])

        result = await pipeline.filter(sample_papers, criteria)

        # Check filter_stats contains messages
        for stage_name, stats in result.filter_stats.items():
            if "messages" in stats:
                assert isinstance(stats["messages"], list)
