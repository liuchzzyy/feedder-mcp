"""AI-powered keyword extraction for paper filtering.

Uses OpenAI-compatible API (DeepSeek, OpenAI, Azure, etc.) to extract
research keywords from a natural-language prompt describing research
interests. Two-stage pipeline: generate candidates → select best 10.
"""

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from openai import OpenAI

from paper_feed.core.config import (
    get_keyword_generator_config,
    get_openai_config,
    get_research_prompt,
)
from paper_feed.core.models import PaperItem

logger = logging.getLogger(__name__)

# Cache file location (project root / cache / keywords_cache.json)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
KEYWORDS_CACHE_FILE = _PROJECT_ROOT / "cache" / "keywords_cache.json"


class KeywordGenerator:
    """Extract and match keywords for paper filtering.

    Uses an OpenAI-compatible LLM to extract research keywords,
    then matches them against paper titles and abstracts using
    flexible multi-strategy matching.

    Attributes:
        api_key: API key for the LLM service.
        model: Model name (e.g. "deepseek-chat", "gpt-4o-mini").
        base_url: Base URL for the API endpoint.
    """

    # Chemical element synonyms: name <-> symbol mappings
    CHEMICAL_SYNONYMS: Dict[str, str] = {
        "zinc": "zn",
        "zn": "zinc",
        "lithium": "li",
        "li": "lithium",
        "sodium": "na",
        "na": "sodium",
        "potassium": "k",
        "k": "potassium",
        "manganese": "mn",
        "mn": "manganese",
        "iron": "fe",
        "fe": "iron",
        "cobalt": "co",
        "co": "cobalt",
        "nickel": "ni",
        "ni": "nickel",
        "copper": "cu",
        "cu": "copper",
        "aluminum": "al",
        "al": "aluminum",
        "aluminium": "al",
        "titanium": "ti",
        "ti": "titanium",
        "vanadium": "v",
        "v": "vanadium",
        "oxygen": "o",
        "o": "oxygen",
        "sulfur": "s",
        "s": "sulfur",
        "sulphur": "s",
        "carbon": "c",
        "c": "carbon",
        "silicon": "si",
        "si": "silicon",
        "phosphorus": "p",
        "p": "phosphorus",
        "magnesium": "mg",
        "mg": "magnesium",
        "calcium": "ca",
        "ca": "calcium",
    }

    # Core scientific terms that match independently
    CORE_TERMS: Set[str] = {
        "operando",
        "in-situ",
        "insitu",
        "in situ",
        "synchrotron",
        "xas",
        "xanes",
        "exafs",
        "xrd",
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        """Initialize the keyword generator.

        Args:
            api_key: API key (defaults to config/env).
            model: Model name (defaults to config/env).
            base_url: API base URL (defaults to config/env).
        """
        config = get_openai_config()
        kg_config = get_keyword_generator_config()
        self.api_key = api_key or config.get("api_key")
        self.model = model or config.get("model", "gpt-4o-mini")
        self.base_url = base_url or config.get("base_url")
        self._generate_max_tokens: int = kg_config.get(
            "generate_max_tokens", 500
        )
        self._select_max_tokens: int = kg_config.get(
            "select_max_tokens", 300
        )
        self._client: Optional[OpenAI] = None
        self._keywords: Optional[List[str]] = None

    @property
    def client(self) -> OpenAI:
        """Lazy-initialize the OpenAI client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError("API key not found. Set OPENAI_API_KEY env var.")
            kwargs: Dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    # -------------------- Keyword Extraction --------------------

    def _generate_candidates(self, research_prompt: str) -> List[str]:
        """Generate candidate keywords from research interests.

        Args:
            research_prompt: Natural-language research description.

        Returns:
            List of candidate keywords.
        """
        system_prompt = (
            "You are an expert scientific keyword extraction assistant.\n"
            "Your task is to analyze the user's research interest prompt "
            "and extract a comprehensive list of 10 highly relevant "
            "English keywords.\n\n"
            "Guidelines:\n"
            "1. **Precision**: Use specific scientific terms "
            '(e.g., "Zn-MnO2 battery", "operando XAS") '
            "rather than broad categories.\n"
            "2. **Coverage**: Include related techniques, materials, "
            "and methods.\n"
            "3. **Variations**: Include common acronyms, chemical "
            'formulas, and synonym variations (e.g., "Li-ion" and '
            '"Lithium-ion").\n'
            "4. **English Only**: All keywords must be in English, "
            "even if the prompt is in another language.\n\n"
            "You MUST respond with ONLY a valid JSON object in this "
            "exact format:\n"
            '{"keywords": ["keyword1", "keyword2", "keyword3", ...]}\n\n'
            "Do not include any other text, explanation, or markdown "
            "formatting."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "Extract keywords from this research "
                            f"interest:\n\n{research_prompt}"
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=self._generate_max_tokens,
            )

            content = response.choices[0].message.content or ""
            return self._parse_keywords_json(content)

        except Exception as e:
            logger.error(f"Error generating candidate keywords: {e}")
            return []

    def _select_best_keywords(self, candidates: List[str]) -> List[str]:
        """Select the 10 best keywords from candidates.

        Args:
            candidates: List of candidate keywords.

        Returns:
            List of up to 10 selected keywords.
        """
        if len(candidates) <= 10:
            return candidates

        unique_candidates = list(set(candidates))
        if len(unique_candidates) <= 10:
            return unique_candidates

        system_prompt = (
            "You are a keyword selection expert.\n"
            "From the provided list of candidate keywords, select "
            "the 10 BEST keywords that:\n"
            "1. Are most specific and precise\n"
            "2. Cover diverse aspects of the research area\n"
            "3. Are most likely to match relevant paper titles\n\n"
            "You MUST respond with ONLY a valid JSON object in this "
            "exact format:\n"
            '{"keywords": ["keyword1", "keyword2", ...]}\n\n'
            "Select exactly 10 keywords. Do not include any other "
            "text."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            "Select the 10 best keywords from:\n"
                            f"{json.dumps(unique_candidates)}"
                        ),
                    },
                ],
                temperature=0.0,
                max_tokens=self._select_max_tokens,
            )

            content = response.choices[0].message.content or ""
            return self._parse_keywords_json(content)[:10]

        except Exception as e:
            logger.error(f"Error selecting best keywords: {e}")
            return unique_candidates[:10]

    def _parse_keywords_json(self, content: str) -> List[str]:
        """Parse keywords from JSON response with fallback handling.

        Tries 4 strategies:
        1. Direct JSON parse
        2. Extract from markdown code block
        3. Extract JSON array
        4. Regex fallback for quoted strings

        Args:
            content: Raw LLM response text.

        Returns:
            List of keyword strings.
        """
        content = content.strip()

        # Strategy 1: Direct JSON parse
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "keywords" in data:
                return [str(k) for k in data["keywords"] if k]
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                if isinstance(data, dict) and "keywords" in data:
                    return [str(k) for k in data["keywords"] if k]
            except json.JSONDecodeError:
                pass

        # Strategy 3: Extract array from content
        array_match = re.search(r'\["[^"]+(?:",\s*"[^"]+)*"\]', content)
        if array_match:
            try:
                keywords = json.loads(array_match.group(0))
                return [str(k) for k in keywords if k]
            except json.JSONDecodeError:
                pass

        # Strategy 4: Last resort — extract quoted strings
        logger.warning("Failed to parse JSON, falling back to text extraction")
        keywords = re.findall(r'"([^"]+)"', content)
        if keywords:
            return keywords

        return []

    async def extract_keywords(
        self,
        research_prompt: Optional[str] = None,
        num_parallel_calls: int = 3,
    ) -> List[str]:
        """Extract keywords from research interests.

        Two-stage pipeline:
        1. Generate candidates with parallel API calls.
        2. Select the best 10 keywords.

        Results are cached using SHA256 hash of the prompt.

        Args:
            research_prompt: Research description text.
                Falls back to config if not provided.
            num_parallel_calls: Number of parallel candidate calls.

        Returns:
            List of up to 10 keywords.

        Raises:
            ValueError: If no research prompt is available.
        """
        if research_prompt is None:
            research_prompt = get_research_prompt()
        if not research_prompt:
            raise ValueError(
                "No research prompt available. Set RESEARCH_PROMPT "
                "env var or pass prompt directly."
            )

        # Check cache
        prompt_hash = hashlib.sha256(research_prompt.encode("utf-8")).hexdigest()

        if KEYWORDS_CACHE_FILE.exists():
            try:
                cache_data = json.loads(KEYWORDS_CACHE_FILE.read_text(encoding="utf-8"))
                if cache_data.get("hash") == prompt_hash:
                    cached = cache_data.get("keywords", [])
                    if cached:
                        logger.info("Using cached keywords (prompt unchanged)")
                        self._keywords = cached
                        return cached
            except Exception as e:
                logger.warning(f"Failed to load keyword cache: {e}")

        # Stage 1: Generate candidates in parallel
        logger.info(
            f"Generating candidates with {num_parallel_calls} parallel calls..."
        )

        futures = [
            asyncio.to_thread(self._generate_candidates, research_prompt)
            for _ in range(num_parallel_calls)
        ]
        results = await asyncio.gather(*futures)

        # Flatten and deduplicate
        all_candidates: List[str] = []
        for result in results:
            all_candidates.extend(result)

        unique_candidates = list(set(all_candidates))
        logger.info(f"Generated {len(unique_candidates)} unique candidates")

        if not unique_candidates:
            logger.error("No keywords generated. Check API key and prompt.")
            return []

        # Stage 2: Select best keywords
        logger.info("Selecting best 10 keywords...")
        best_keywords = await asyncio.to_thread(
            self._select_best_keywords, unique_candidates
        )

        # Save to cache
        try:
            KEYWORDS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "hash": prompt_hash,
                "keywords": best_keywords,
            }
            KEYWORDS_CACHE_FILE.write_text(
                json.dumps(cache_data, indent=2), encoding="utf-8"
            )
            logger.info(f"Saved keywords to cache: {KEYWORDS_CACHE_FILE}")
        except Exception as e:
            logger.warning(f"Failed to save keyword cache: {e}")

        self._keywords = best_keywords
        logger.info(f"Final keywords: {best_keywords}")
        return best_keywords

    # -------------------- Text Matching --------------------

    def _normalize_text(self, text: str) -> str:
        """Normalize text for flexible matching.

        Args:
            text: Input text.

        Returns:
            Lowercased, cleaned text with hyphens/punctuation
            replaced by spaces.
        """
        text = text.lower()
        text = re.sub(r"[-_]", " ", text)
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _get_word_stem(self, word: str) -> str:
        """Get simple stem of a word.

        Args:
            word: Input word.

        Returns:
            Stemmed word (simple suffix removal).
        """
        word = word.lower()
        if word.endswith("ies") and len(word) > 3:
            return word[:-3] + "y"
        elif word.endswith("es") and len(word) > 2:
            return word[:-2]
        elif word.endswith("s") and len(word) > 2 and not word.endswith("ss"):
            return word[:-1]
        elif word.endswith("ed") and len(word) > 2:
            return word[:-2]
        elif word.endswith("ing") and len(word) > 3:
            return word[:-3]
        return word

    def _get_word_stems(self, text: str) -> Set[str]:
        """Extract word stems from text.

        Args:
            text: Input text.

        Returns:
            Set of stemmed words.
        """
        words = self._normalize_text(text).split()
        return {self._get_word_stem(w) for w in words}

    def _expand_with_synonyms(self, text: str) -> str:
        """Expand text with chemical synonyms.

        Args:
            text: Normalized input text.

        Returns:
            Text with synonym expansions appended.
        """
        words = text.lower().split()
        expanded: List[str] = []
        for word in words:
            expanded.append(word)
            if word in self.CHEMICAL_SYNONYMS:
                expanded.append(self.CHEMICAL_SYNONYMS[word])
        return " ".join(expanded)

    def _matches_keyword(self, text: str, keyword: str) -> bool:
        """Check if text matches a keyword using flexible matching.

        Five strategies (tried in order):
        1. Exact substring (after normalization)
        2. All keyword words appear in text
        3. Stem-based matching
        4. Chemical synonym matching
        5. Core term matching

        Args:
            text: Paper title + abstract text.
            keyword: Keyword to match against.

        Returns:
            True if any strategy matches.
        """
        text_norm = self._normalize_text(text)
        kw_norm = self._normalize_text(keyword)

        # Strategy 1: Exact substring
        if kw_norm in text_norm:
            return True

        # Strategy 2: All keyword words in text
        kw_words = set(kw_norm.split())
        text_words = set(text_norm.split())
        if kw_words and kw_words.issubset(text_words):
            return True

        # Strategy 3: Stem-based matching
        text_stems = self._get_word_stems(text)
        kw_stems = self._get_word_stems(keyword)
        if kw_stems and kw_stems.issubset(text_stems):
            return True

        # Strategy 4: Chemical synonym matching
        text_expanded = self._expand_with_synonyms(text_norm)
        kw_expanded = self._expand_with_synonyms(kw_norm)
        text_exp_words = set(text_expanded.split())
        kw_exp_words = set(kw_expanded.split())
        if kw_exp_words and kw_exp_words.issubset(text_exp_words):
            return True

        # Strategy 5: Core term matching
        kw_words_lower = {w.lower() for w in kw_norm.split()}
        text_words_lower = {w.lower() for w in text_norm.split()}
        for core_term in self.CORE_TERMS:
            core_norm = self._normalize_text(core_term)
            core_words = set(core_norm.split())
            if core_words.issubset(kw_words_lower) or core_norm in kw_norm:
                if core_words.issubset(text_words_lower) or core_norm in text_norm:
                    return True

        return False

    def filter_items(
        self,
        items: List[PaperItem],
        keywords: Optional[List[str]] = None,
    ) -> Tuple[List[PaperItem], List[PaperItem]]:
        """Filter papers by matching keywords against title+abstract.

        Args:
            items: Papers to filter.
            keywords: Keywords to match (uses cached if not provided).

        Returns:
            Tuple of (relevant_papers, irrelevant_papers).

        Raises:
            ValueError: If no keywords are available.
        """
        kw_list = keywords or self._keywords
        if not kw_list:
            raise ValueError(
                "No keywords available. Call extract_keywords() first "
                "or provide keywords."
            )

        relevant: List[PaperItem] = []
        irrelevant: List[PaperItem] = []

        for item in items:
            text = f"{item.title} {item.abstract}"
            is_relevant = any(self._matches_keyword(text, kw) for kw in kw_list)

            if is_relevant:
                relevant.append(item)
                logger.debug(f"  ✓ Matched: {item.title[:60]}...")
            else:
                irrelevant.append(item)
                logger.debug(f"  ✗ No match: {item.title[:60]}...")

        logger.info(
            f"Filtering complete: {len(relevant)} relevant, "
            f"{len(irrelevant)} irrelevant"
        )
        return relevant, irrelevant

    async def filter_with_keywords(
        self,
        items: List[PaperItem],
        research_prompt: Optional[str] = None,
    ) -> Tuple[List[PaperItem], List[PaperItem], List[str]]:
        """Full pipeline: extract keywords then filter items.

        Args:
            items: Papers to filter.
            research_prompt: Research description (optional).

        Returns:
            Tuple of (relevant, irrelevant, keywords_used).
        """
        keywords = await self.extract_keywords(research_prompt)
        if not keywords:
            logger.warning("No keywords extracted. Returning all as irrelevant.")
            return [], items, []

        relevant, irrelevant = self.filter_items(items, keywords)
        return relevant, irrelevant, keywords
