"""Filter pipeline for applying multiple filter stages."""

import logging
from typing import Any, Dict, List

from paper_feed.core.models import FilterCriteria, FilterResult, PaperItem
from paper_feed.filters.keyword import KeywordFilterStage

logger = logging.getLogger(__name__)


class FilterPipeline:
    """Pipeline for applying multiple filter stages to papers.

    The pipeline applies filter stages in sequence, with each stage
    processing the output of the previous stage:
    - Stage 1: KeywordFilterStage (keyword, category, author, date, PDF)
    - Stage 2: AIFilterStage (LLM-based relevance, optional)
    """

    def __init__(self, llm_client=None) -> None:
        """Initialize filter pipeline.

        Args:
            llm_client: Optional OpenAI client for AI-powered
                filtering. If provided, AIFilterStage is enabled.
        """
        self.keyword_stage = KeywordFilterStage()
        self.llm_client = llm_client
        self._ai_stage = None

        if llm_client is not None:
            try:
                from paper_feed.filters.ai_filter import (
                    AIFilterStage,
                )

                self._ai_stage = AIFilterStage(openai_client=llm_client)
            except ImportError:
                logger.warning(
                    "AI filter requested but paper_feed.ai module not available"
                )

    async def filter(
        self,
        papers: List[PaperItem],
        criteria: FilterCriteria,
    ) -> FilterResult:
        """Apply filter pipeline to papers.

        Args:
            papers: List of papers to filter.
            criteria: Filter criteria to apply.

        Returns:
            FilterResult with filtered papers and statistics.
        """
        total_count = len(papers)
        filter_stats: Dict[str, Any] = {}

        # Stage 1: Keyword-based filtering
        if self.keyword_stage.is_applicable(criteria):
            papers, messages = await self.keyword_stage.filter(papers, criteria)
            filter_stats["keyword_filter"] = {
                "input_count": total_count,
                "output_count": len(papers),
                "messages": messages,
            }
        else:
            filter_stats["keyword_filter"] = {
                "skipped": True,
                "reason": "No keyword criteria specified",
            }

        # Stage 2: AI-based filtering (optional)
        if self._ai_stage is not None and self._ai_stage.is_applicable(criteria):
            ai_input_count = len(papers)
            papers, messages = await self._ai_stage.filter(papers, criteria)
            filter_stats["ai_filter"] = {
                "input_count": ai_input_count,
                "output_count": len(papers),
                "messages": messages,
            }
        else:
            reason = (
                "No LLM client configured"
                if self._ai_stage is None
                else "AI stage not applicable"
            )
            filter_stats["ai_filter"] = {
                "skipped": True,
                "reason": reason,
            }

        # Build final result
        passed_count = len(papers)
        rejected_count = total_count - passed_count

        return FilterResult(
            papers=papers,
            total_count=total_count,
            passed_count=passed_count,
            rejected_count=rejected_count,
            filter_stats=filter_stats,
        )
