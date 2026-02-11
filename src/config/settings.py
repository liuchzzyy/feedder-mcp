"""Centralized settings using pydantic-settings.

All configuration is loaded from environment variables and .env files.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Project root: three levels up from this file (src/config/settings.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_dotenv_loaded = False


class PaperFeedSettings(BaseSettings):
    """Feedder-mcp configuration loaded from env vars / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Server ----
    server_name: str = "feedder-mcp"

    # ---- RSS ----
    paper_feed_opml: str = Field(
        default="feeds/RSS_official.opml",
        validation_alias="FEEDDER_MCP_OPML",
    )
    paper_feed_user_agent: str = Field(
        default="feedder-mcp/2.0",
        validation_alias="FEEDDER_MCP_USER_AGENT",
    )
    rss_timeout: int = 30
    rss_max_concurrent: int = 10

    # ---- Gmail ----
    gmail_token_json: Optional[str] = None
    gmail_credentials_json: Optional[str] = None
    gmail_token_file: str = "feeds/token.json"
    gmail_credentials_file: str = "feeds/credentials.json"
    gmail_query: Optional[str] = None
    gmail_max_results: int = 50
    gmail_mark_as_read: bool = False
    gmail_trash_after_process: bool = True
    gmail_verify_trash_after_process: bool = True
    gmail_verify_trash_limit: int = 50
    gmail_processed_label: Optional[str] = None
    gmail_sender_filter: Optional[str] = None
    gmail_sender_map_json: Optional[str] = None

    # ---- OpenAI / LLM ----
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: Optional[str] = None

    # ---- Research Prompt ----
    research_prompt: Optional[str] = None
    research_prompt_file: Optional[str] = None

    # ---- AI Filter ----
    ai_batch_size: int = 50
    ai_filter_max_tokens: int = 1000

    # ---- Keyword Generator ----
    keyword_generate_max_tokens: int = 500
    keyword_select_max_tokens: int = 300

    # ---- Metadata APIs (shared) ----
    polite_pool_email: Optional[str] = None
    api_timeout: float = 45.0
    api_user_agent: str = (
        "feedder-mcp/2.0 (https://github.com/feedder-mcp; mailto:{email})"
    )

    # ---- CrossRef ----
    crossref_email: Optional[str] = None
    crossref_api_base: str = "https://api.crossref.org"
    crossref_timeout: Optional[float] = None
    crossref_user_agent: Optional[str] = None

    # ---- OpenAlex ----
    openalex_email: Optional[str] = None
    openalex_api_key: Optional[str] = None
    openalex_api_base: str = "https://api.openalex.org"
    openalex_timeout: Optional[float] = None
    openalex_user_agent: Optional[str] = None
    openalex_max_requests_per_second: int = 10

    # ---- Zotero ----
    zotero_library_id: str = ""
    zotero_api_key: str = ""
    zotero_library_type: str = "user"

    # ---- Derived accessors (compatibility with old config functions) ----

    def get_openai_config(self) -> dict:
        return {
            "api_key": self.openai_api_key,
            "model": self.openai_model,
            "base_url": self.openai_base_url,
        }

    def get_gmail_config(self) -> dict:
        return {
            "token_json": self.gmail_token_json,
            "credentials_json": self.gmail_credentials_json,
            "token_file": self.gmail_token_file,
            "credentials_file": self.gmail_credentials_file,
            "query": self.gmail_query,
            "max_results": self.gmail_max_results,
            "mark_as_read": self.gmail_mark_as_read,
            "trash_after_process": self.gmail_trash_after_process,
            "verify_trash_after_process": self.gmail_verify_trash_after_process,
            "verify_trash_limit": self.gmail_verify_trash_limit,
            "processed_label": self.gmail_processed_label,
            "sender_filter": self.gmail_sender_filter,
            "sender_map_json": self.gmail_sender_map_json,
        }

    def get_rss_config(self) -> dict:
        return {
            "opml_path": self.paper_feed_opml,
            "user_agent": self.paper_feed_user_agent,
            "timeout": self.rss_timeout,
            "max_concurrent": self.rss_max_concurrent,
        }

    def get_crossref_config(self) -> dict:
        return {
            "email": self.crossref_email or self.polite_pool_email,
            "api_base": self.crossref_api_base,
            "timeout": self.crossref_timeout or self.api_timeout,
            "user_agent": self.crossref_user_agent or self.api_user_agent,
        }

    def get_openalex_config(self) -> dict:
        return {
            "email": self.openalex_email or self.polite_pool_email,
            "api_key": self.openalex_api_key,
            "api_base": self.openalex_api_base,
            "timeout": self.openalex_timeout or self.api_timeout,
            "user_agent": self.openalex_user_agent or self.api_user_agent,
            "max_requests_per_second": self.openalex_max_requests_per_second,
        }

    def get_zotero_config(self) -> dict:
        return {
            "library_id": self.zotero_library_id,
            "api_key": self.zotero_api_key,
            "library_type": self.zotero_library_type,
        }

    def get_research_prompt(self) -> Optional[str]:
        """Get research prompt from env var or file."""
        if self.research_prompt and self.research_prompt.strip():
            return self.research_prompt.strip()
        if self.research_prompt_file:
            path = Path(self.research_prompt_file)
            if path.exists():
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content
        return None

    def get_ai_filter_config(self) -> dict:
        return {
            "batch_size": self.ai_batch_size,
            "max_tokens": self.ai_filter_max_tokens,
        }

    def get_keyword_generator_config(self) -> dict:
        return {
            "generate_max_tokens": self.keyword_generate_max_tokens,
            "select_max_tokens": self.keyword_select_max_tokens,
        }


settings = PaperFeedSettings(_env_file=None)


def _ensure_dotenv() -> None:
    """Load .env file once for compatibility with legacy config tests."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
    else:
        load_dotenv(override=True)
    _dotenv_loaded = True


def reload_config() -> PaperFeedSettings:
    """Reload settings from environment and .env file."""
    global settings
    global _dotenv_loaded
    _dotenv_loaded = False
    _ensure_dotenv()
    settings = PaperFeedSettings()
    return settings


def get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Get an environment variable with optional default."""
    _ensure_dotenv()
    return os.environ.get(name, default)


def _fresh_settings() -> PaperFeedSettings:
    _ensure_dotenv()
    return PaperFeedSettings(_env_file=None)


def get_settings() -> PaperFeedSettings:
    """Get settings with .env loaded into environment."""
    return _fresh_settings()


def get_openai_config() -> dict:
    return _fresh_settings().get_openai_config()


def get_gmail_config() -> dict:
    return _fresh_settings().get_gmail_config()


def get_rss_config() -> dict:
    return _fresh_settings().get_rss_config()


def get_crossref_config() -> dict:
    return _fresh_settings().get_crossref_config()


def get_openalex_config() -> dict:
    return _fresh_settings().get_openalex_config()


def get_zotero_config() -> dict:
    return _fresh_settings().get_zotero_config()


def get_research_prompt() -> Optional[str]:
    return _fresh_settings().get_research_prompt()


def get_ai_filter_config() -> dict:
    return _fresh_settings().get_ai_filter_config()


def get_keyword_generator_config() -> dict:
    return _fresh_settings().get_keyword_generator_config()
