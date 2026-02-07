"""Configuration loading and management for paper-feed.

Loads configuration from environment variables and .env files using
python-dotenv. Provides typed accessors for all configurable settings.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# -------------------- .env Loading --------------------

_dotenv_loaded: bool = False


def _ensure_dotenv() -> None:
    """Load .env file once on first access.

    Searches for .env in the current working directory and project root.
    """
    global _dotenv_loaded
    if _dotenv_loaded:
        return

    # Try loading from project root (where pyproject.toml lives)
    project_root = Path(__file__).resolve().parents[3]
    dotenv_path = project_root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path, override=True)
        logger.debug(f"Loaded .env from {dotenv_path}")
    else:
        # Fallback: search upward from cwd
        load_dotenv(override=True)
        logger.debug("Loaded .env from default search path")

    _dotenv_loaded = True


def reload_config() -> None:
    """Force reload .env file (useful for testing)."""
    global _dotenv_loaded
    _dotenv_loaded = False
    _ensure_dotenv()


# -------------------- Accessors --------------------


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get an environment variable, loading .env first if needed.

    Args:
        key: Environment variable name.
        default: Default value if not set.

    Returns:
        Value of the environment variable, or default.
    """
    _ensure_dotenv()
    return os.environ.get(key, default)


def get_openai_config() -> Dict[str, Any]:
    """Get OpenAI API configuration.

    Returns:
        Dict with api_key, model, base_url settings.
    """
    _ensure_dotenv()
    return {
        "api_key": os.environ.get("OPENAI_API_KEY"),
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "base_url": os.environ.get("OPENAI_BASE_URL"),
    }


def get_gmail_config() -> Dict[str, Any]:
    """Get Gmail/EZGmail configuration.

    Supports inline JSON mode for OAuth2 credentials only:
    - GMAIL_TOKEN_JSON: OAuth2 token JSON string (required)
    - GMAIL_CREDENTIALS_JSON: OAuth2 credentials JSON string (required)

    The JSON values are written to fixed file paths (token.json /
    credentials.json) before EZGmail initialization for compatibility.

    Returns:
        Dict with token_json, credentials_json, query, max_results,
        mark_as_read, processed_label, sender_filter settings.
    """
    _ensure_dotenv()
    return {
        "token_json": os.environ.get("GMAIL_TOKEN_JSON"),
        "credentials_json": os.environ.get("GMAIL_CREDENTIALS_JSON"),
        "query": os.environ.get("GMAIL_QUERY", "label:UNREAD"),
        "max_results": int(os.environ.get("GMAIL_MAX_RESULTS", "50")),
        "mark_as_read": os.environ.get("GMAIL_MARK_AS_READ", "false").lower()
        in ("true", "1", "yes"),
        "processed_label": os.environ.get("GMAIL_PROCESSED_LABEL"),
        "sender_filter": os.environ.get("GMAIL_SENDER_FILTER"),
    }


def get_zotero_config() -> Dict[str, Any]:
    """Get Zotero API configuration.

    Returns:
        Dict with library_id, api_key, library_type settings.
    """
    _ensure_dotenv()
    return {
        "library_id": os.environ.get("ZOTERO_LIBRARY_ID", ""),
        "api_key": os.environ.get("ZOTERO_API_KEY", ""),
        "library_type": os.environ.get("ZOTERO_LIBRARY_TYPE", "user"),
    }


def get_rss_config() -> Dict[str, Any]:
    """Get RSS source configuration.

    Returns:
        Dict with opml_path, user_agent, timeout, max_concurrent settings.
    """
    _ensure_dotenv()
    return {
        "opml_path": os.environ.get("PAPER_FEED_OPML", "feeds/RSS_official.opml"),
        "user_agent": os.environ.get("PAPER_FEED_USER_AGENT", "paper-feed/1.0"),
        "timeout": int(os.environ.get("RSS_TIMEOUT", "30")),
        "max_concurrent": int(os.environ.get("RSS_MAX_CONCURRENT", "10")),
    }


def _get_shared_api_defaults() -> Dict[str, Any]:
    """Get shared defaults for metadata API clients (CrossRef, OpenAlex).

    Reads POLITE_POOL_EMAIL, API_TIMEOUT, and API_USER_AGENT as shared
    fallbacks. Per-service env vars (CROSSREF_*, OPENALEX_*) take priority.
    """
    return {
        "email": os.environ.get("POLITE_POOL_EMAIL"),
        "timeout": float(os.environ.get("API_TIMEOUT", "45.0")),
        "user_agent": os.environ.get(
            "API_USER_AGENT",
            "paper-feed/1.0 (https://github.com/paper-feed; mailto:{email})",
        ),
    }


def get_crossref_config() -> Dict[str, Any]:
    """Get CrossRef API configuration.

    Falls back to shared API defaults (POLITE_POOL_EMAIL, API_TIMEOUT,
    API_USER_AGENT) when per-service env vars are not set.

    Returns:
        Dict with email, api_base, timeout, user_agent settings.
    """
    _ensure_dotenv()
    shared = _get_shared_api_defaults()
    return {
        "email": os.environ.get("CROSSREF_EMAIL") or shared["email"],
        "api_base": os.environ.get("CROSSREF_API_BASE", "https://api.crossref.org"),
        "timeout": float(os.environ.get("CROSSREF_TIMEOUT", str(shared["timeout"]))),
        "user_agent": os.environ.get("CROSSREF_USER_AGENT") or shared["user_agent"],
    }


def get_openalex_config() -> Dict[str, Any]:
    """Get OpenAlex API configuration.

    Falls back to shared API defaults (POLITE_POOL_EMAIL, API_TIMEOUT,
    API_USER_AGENT) when per-service env vars are not set.

    Returns:
        Dict with email, api_base, timeout, user_agent settings.
    """
    _ensure_dotenv()
    shared = _get_shared_api_defaults()
    return {
        "email": os.environ.get("OPENALEX_EMAIL") or shared["email"],
        "api_base": os.environ.get("OPENALEX_API_BASE", "https://api.openalex.org"),
        "timeout": float(os.environ.get("OPENALEX_TIMEOUT", str(shared["timeout"]))),
        "user_agent": os.environ.get("OPENALEX_USER_AGENT") or shared["user_agent"],
    }


def get_research_prompt() -> Optional[str]:
    """Get research interests prompt text.

    Loaded from RESEARCH_PROMPT env var or from a prompt file path
    specified by RESEARCH_PROMPT_FILE env var.

    Returns:
        Research prompt text, or None if not configured.
    """
    _ensure_dotenv()

    # Direct prompt text
    prompt = os.environ.get("RESEARCH_PROMPT")
    if prompt and prompt.strip():
        return prompt.strip()

    # Prompt file
    prompt_file = os.environ.get("RESEARCH_PROMPT_FILE")
    if prompt_file:
        path = Path(prompt_file)
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                return content

    return None


def get_ai_filter_config() -> Dict[str, Any]:
    """Get AI filter stage configuration.

    Returns:
        Dict with batch_size, max_tokens settings.
    """
    _ensure_dotenv()
    return {
        "batch_size": int(os.environ.get("AI_BATCH_SIZE", "50")),
        "max_tokens": int(os.environ.get("AI_FILTER_MAX_TOKENS", "1000")),
    }


def get_keyword_generator_config() -> Dict[str, Any]:
    """Get keyword generator configuration.

    Returns:
        Dict with generate_max_tokens, select_max_tokens settings.
    """
    _ensure_dotenv()
    return {
        "generate_max_tokens": int(
            os.environ.get("KEYWORD_GENERATE_MAX_TOKENS", "500")
        ),
        "select_max_tokens": int(os.environ.get("KEYWORD_SELECT_MAX_TOKENS", "300")),
    }
