"""AI-powered filter stage for the paper filtering pipeline.

Uses an OpenAI-compatible LLM to judge paper relevance based on
research interests. Designed to integrate as Stage 2 in the
FilterPipeline after keyword-based filtering.
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from openai import OpenAI

from paper_feed.core.config import (
    get_ai_filter_config,
    get_openai_config,
    get_research_prompt,
)
from paper_feed.core.models import FilterCriteria, PaperItem

logger = logging.getLogger(__name__)


class AIFilterStage:
    """Filter papers using LLM-based relevance judgement.

    Sends batches of papers with a research interest prompt to an LLM,
    which returns indices of relevant papers as JSON.

    This stage is designed to be used in FilterPipeline as Stage 2,
    after keyword-based filtering narrows the candidate set.
    """

    def __init__(
        self,
        openai_client: Optional[OpenAI] = None,
        model: Optional[str] = None,
    ) -> None:
        """Initialize the AI filter stage.

        Args:
            openai_client: Pre-configured OpenAI client.
                Created from config if not provided.
            model: Model name override.
        """
        config = get_openai_config()
        ai_config = get_ai_filter_config()
        self.model = model or config.get("model", "gpt-4o-mini")
        self._batch_size: int = ai_config.get("batch_size", 50)
        self._max_tokens: int = ai_config.get("max_tokens", 1000)

        if openai_client is not None:
            self._client = openai_client
        else:
            api_key = config.get("api_key")
            if api_key:
                kwargs: Dict[str, Any] = {"api_key": api_key}
                base_url = config.get("base_url")
                if base_url:
                    kwargs["base_url"] = base_url
                self._client = OpenAI(**kwargs)
            else:
                self._client = None

    def is_applicable(self, criteria: FilterCriteria) -> bool:
        """Check if AI filtering is available.

        Args:
            criteria: Filter criteria (unused, always applicable
                if client is configured).

        Returns:
            True if an OpenAI client is available.
        """
        return self._client is not None

    async def filter(
        self,
        papers: List[PaperItem],
        criteria: FilterCriteria,
    ) -> Tuple[List[PaperItem], List[str]]:
        """Apply AI-based filtering to papers.

        Args:
            papers: List of papers to filter.
            criteria: Filter criteria (used for context).

        Returns:
            Tuple of (filtered_papers, filter_messages).
        """
        messages: List[str] = []

        if self._client is None:
            messages.append("AI filter skipped: no API key configured")
            return papers, messages

        research_prompt = get_research_prompt()
        if not research_prompt:
            messages.append(
                "AI filter skipped: no research prompt configured. "
                "Set RESEARCH_PROMPT env var."
            )
            return papers, messages

        if not papers:
            return papers, messages

        # Process in batches
        all_relevant_indices: Set[int] = set()

        for batch_start in range(0, len(papers), self._batch_size):
            batch = papers[batch_start : batch_start + self._batch_size]
            batch_indices = await self._filter_batch(
                batch, research_prompt, batch_start
            )
            all_relevant_indices.update(batch_indices)

        # Split into relevant / irrelevant
        relevant = [papers[i] for i in sorted(all_relevant_indices)]
        irrelevant_count = len(papers) - len(relevant)

        messages.append(
            f"AI filter: {len(relevant)} relevant, "
            f"{irrelevant_count} irrelevant "
            f"out of {len(papers)} total"
        )

        logger.info(
            f"AI filtering complete: {len(relevant)} relevant, "
            f"{irrelevant_count} irrelevant"
        )
        return relevant, messages

    async def _filter_batch(
        self,
        batch: List[PaperItem],
        research_prompt: str,
        global_offset: int,
    ) -> Set[int]:
        """Run LLM filtering on one batch of papers.

        Args:
            batch: Papers in this batch.
            research_prompt: Research interest text.
            global_offset: Starting index in the full list.

        Returns:
            Set of global indices that are relevant.
        """
        assert self._client is not None
        papers_text = self._build_papers_text(batch)

        prompt_content = (
            f"## 研究兴趣\n\n{research_prompt}\n\n"
            f"## 论文列表\n\n"
            f"以下是 {len(batch)} 篇论文的标题和摘要。"
            f"请判断每篇论文是否与上述研究兴趣相关。\n\n"
            f"{papers_text}\n\n"
            f"## 输出要求\n\n"
            f"请仅输出一个 JSON 对象，标注与研究兴趣相关的"
            f"论文编号（从 0 开始的索引）。\n"
            f'{{"relevant": [0, 3, 7, ...]}}\n\n'
            f"只输出 JSON，不要输出任何其他文本或解释。\n"
            f'{{"relevant": []}}'
        )

        try:
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个学术论文相关性判断助手。"
                            "请根据用户的研究兴趣，判断论文列表中"
                            "哪些论文与研究兴趣相关。"
                            "仅输出JSON格式结果。"
                        ),
                    },
                    {"role": "user", "content": prompt_content},
                ],
                temperature=0.0,
                max_tokens=self._max_tokens,
            )

            output = response.choices[0].message.content or ""  # type: ignore[union-attr]
            batch_indices = self._parse_filter_output(output, len(batch))

            # Convert batch-local to global indices
            return {global_offset + i for i in batch_indices}

        except Exception as e:
            logger.error(
                f"AI filter batch failed (offset={global_offset}): "
                f"{e}. Treating all {len(batch)} papers as relevant."
            )
            # On failure, keep all papers (fail-open)
            return {global_offset + i for i in range(len(batch))}

    def _build_papers_text(self, items: List[PaperItem]) -> str:
        """Build numbered paper list for LLM prompt.

        Args:
            items: Papers to format.

        Returns:
            Formatted text with numbered entries.
        """
        lines: List[str] = []
        for i, item in enumerate(items):
            abstract = (item.abstract or "").strip()
            if len(abstract) > 500:
                abstract = abstract[:500] + "..."
            lines.append(f"### [{i}] {item.title}")
            if abstract:
                lines.append(abstract)
            lines.append("")
        return "\n".join(lines)

    def _parse_filter_output(self, output: str, batch_size: int) -> Set[int]:
        """Parse LLM output to extract relevant paper indices.

        Tries 3 strategies:
        1. Direct JSON parse
        2. Extract from markdown code block
        3. Find JSON object anywhere in output

        Args:
            output: Raw LLM response text.
            batch_size: Number of papers in the batch.

        Returns:
            Set of valid indices within [0, batch_size).
        """
        output = output.strip()

        # Strategy 1: Direct JSON parse
        try:
            data = json.loads(output)
            if isinstance(data, dict) and "relevant" in data:
                return self._validate_indices(data["relevant"], batch_size)
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract from markdown code blocks
        json_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            output,
            re.DOTALL,
        )
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if isinstance(data, dict) and "relevant" in data:
                    return self._validate_indices(data["relevant"], batch_size)
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find JSON object anywhere
        json_obj_match = re.search(
            r'\{[^{}]*"relevant"\s*:\s*\[.*?\][^{}]*\}',
            output,
            re.DOTALL,
        )
        if json_obj_match:
            try:
                data = json.loads(json_obj_match.group(0))
                if isinstance(data, dict) and "relevant" in data:
                    return self._validate_indices(data["relevant"], batch_size)
            except json.JSONDecodeError:
                pass

        logger.warning(f"Failed to parse AI filter output. Preview: {output[:200]}")
        return set()

    def _validate_indices(self, indices: List[Any], batch_size: int) -> Set[int]:
        """Validate and filter indices to be within range.

        Args:
            indices: List of raw index values.
            batch_size: Maximum valid index (exclusive).

        Returns:
            Set of valid integer indices.
        """
        valid: Set[int] = set()
        for idx in indices:
            try:
                i = int(idx)
                if 0 <= i < batch_size:
                    valid.add(i)
                else:
                    logger.warning(f"Index {i} out of range [0, {batch_size})")
            except (ValueError, TypeError):
                logger.warning(f"Invalid index value: {idx}")
        return valid
