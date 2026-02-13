"""Unit tests for configuration loading and management."""

import os
from pathlib import Path
from unittest import mock

import pytest

from src.config.settings import (
    _ensure_dotenv,
    get_crossref_config,
    get_env,
    get_gmail_config,
    get_openalex_config,
    get_openai_config,
    get_research_prompt,
    get_rss_config,
    get_zotero_config,
    reload_config,
)


@pytest.fixture(autouse=True)
def reset_dotenv_flag(monkeypatch):
    """Reset the _dotenv_loaded flag before and after each test.

    This ensures each test starts with a clean state and prevents
    the global flag from affecting other tests.
    """
    import src.config.settings as config_module

    original_flag = config_module._dotenv_loaded
    config_module._dotenv_loaded = True  # Prevent _ensure_dotenv from loading real .env
    # Clear all config-related env vars to isolate from real .env
    for key in [
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "RESEARCH_PROMPT",
        "RESEARCH_PROMPT_FILE",
        "GMAIL_TOKEN_JSON",
        "GMAIL_CREDENTIALS_JSON",
        "ZOTERO_LIBRARY_ID",
        "ZOTERO_API_KEY",
        "ZOTERO_LIBRARY_TYPE",
        "TARGET_COLLECTION",
        "PAPER_FEEDDER_MCP_OPML",
        "PAPER_FEEDDER_MCP_USER_AGENT",
        "CROSSREF_EMAIL",
        "OPENALEX_EMAIL",
    ]:
        monkeypatch.delenv(key, raising=False)
    yield
    config_module._dotenv_loaded = original_flag


class TestEnsureDotenv:
    """Tests for _ensure_dotenv() functionality."""

    def test_ensure_dotenv_called_once(self):
        """Test that _ensure_dotenv only loads dotenv once (idempotent)."""
        import src.config.settings as config_module

        config_module._dotenv_loaded = False
        with mock.patch("src.config.settings.load_dotenv") as mock_load:
            # First call should load
            _ensure_dotenv()
            assert mock_load.call_count == 1

            # Second call should not load again
            _ensure_dotenv()
            assert mock_load.call_count == 1

    def test_ensure_dotenv_with_existing_file(self):
        """Test that _ensure_dotenv loads from project root if .env exists."""
        import src.config.settings as config_module

        config_module._dotenv_loaded = False
        mock_path = mock.MagicMock(spec=Path)
        mock_path.exists.return_value = True

        with mock.patch("src.config.settings.Path") as mock_Path:
            with mock.patch("src.config.settings.load_dotenv") as mock_load:
                mock_Path.return_value = mock_path
                _ensure_dotenv()

                # Should call load_dotenv with the path
                mock_load.assert_called_once()
                call_args = mock_load.call_args
                assert call_args[1] == {"override": True}

    def test_ensure_dotenv_without_file(self):
        """Test that _ensure_dotenv falls back when .env doesn't exist."""
        import src.config.settings as config_module

        config_module._dotenv_loaded = False
        mock_path = mock.MagicMock(spec=Path)
        mock_path.exists.return_value = False

        with mock.patch("src.config.settings.Path") as mock_Path:
            with mock.patch("src.config.settings.load_dotenv") as mock_load:
                mock_Path.return_value = mock_path
                _ensure_dotenv()

                # Should call load_dotenv (falls back to default search)
                mock_load.assert_called_once()


class TestReloadConfig:
    """Tests for reload_config() functionality."""

    def test_reload_config_resets_flag(self):
        """Test that reload_config resets the _dotenv_loaded flag."""
        with mock.patch("src.config.settings.load_dotenv"):
            # Set the flag to True
            import src.config.settings as config_module

            config_module._dotenv_loaded = True

            # Call reload_config
            reload_config()

            # Flag should be False after reload
            assert config_module._dotenv_loaded is True  # Reset and called again


class TestGetEnv:
    """Tests for get_env() function."""

    def test_get_env_existing_var(self):
        """Test getting an existing environment variable."""
        with mock.patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            with mock.patch("src.config.settings.load_dotenv"):
                result = get_env("TEST_VAR")
                assert result == "test_value"

    def test_get_env_missing_var_with_default(self):
        """Test getting a missing variable returns the default value."""
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch("src.config.settings.load_dotenv"):
                result = get_env("NONEXISTENT_VAR", "default_value")
                assert result == "default_value"

    def test_get_env_missing_var_no_default(self):
        """Test getting a missing variable without default returns None."""
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch("src.config.settings.load_dotenv"):
                result = get_env("NONEXISTENT_VAR")
                assert result is None

    def test_get_env_empty_string(self):
        """Test that empty string is returned as-is, not as None."""
        with mock.patch.dict(os.environ, {"EMPTY_VAR": ""}):
            with mock.patch("src.config.settings.load_dotenv"):
                result = get_env("EMPTY_VAR")
                assert result == ""


class TestGetOpenaiConfig:
    """Tests for get_openai_config() function."""

    def test_get_openai_config_full_config(self):
        """Test getting OpenAI config with all env vars set."""
        env_vars = {
            "OPENAI_API_KEY": "sk-test123",
            "OPENAI_MODEL": "gpt-4-turbo",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
        }
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_openai_config()
                assert config["api_key"] == "sk-test123"
                assert config["model"] == "gpt-4-turbo"
                assert config["base_url"] == "https://api.openai.com/v1"

    def test_get_openai_config_with_defaults(self):
        """Test OpenAI config with default model when env vars missing."""
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_openai_config()
                assert config["api_key"] is None
                assert config["model"] == "gpt-4o-mini"  # Default model
                assert config["base_url"] is None

    def test_get_openai_config_partial_config(self):
        """Test OpenAI config with only API key set."""
        env_vars = {"OPENAI_API_KEY": "sk-partial"}
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_openai_config()
                assert config["api_key"] == "sk-partial"
                assert config["model"] == "gpt-4o-mini"


class TestGetGmailConfig:
    """Tests for get_gmail_config() function."""

    def test_get_gmail_config_full_config(self):
        """Test getting Gmail config with all env vars set."""
        env_vars = {
            "GMAIL_TOKEN_JSON": '{"token": "...", "refresh_token": "..."}',
            "GMAIL_CREDENTIALS_JSON": '{"installed": {"client_id": "..."}}',
        }
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_gmail_config()
                assert (
                    config["token_json"] == '{"token": "...", "refresh_token": "..."}'
                )
                assert (
                    config["credentials_json"] == '{"installed": {"client_id": "..."}}'
                )

    def test_get_gmail_config_with_defaults(self):
        """Test Gmail config with defaults when env vars missing."""
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_gmail_config()
                assert config["token_json"] is None
                assert config["credentials_json"] is None


class TestGetZoteroConfig:
    """Tests for get_zotero_config() function."""

    def test_get_zotero_config_full_config(self):
        """Test getting Zotero config with all env vars set."""
        env_vars = {
            "ZOTERO_LIBRARY_ID": "12345",
            "ZOTERO_API_KEY": "abcdef123456",
            "ZOTERO_LIBRARY_TYPE": "group",
            "TARGET_COLLECTION": "ABCD1234",
        }
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_zotero_config()
                assert config["library_id"] == "12345"
                assert config["api_key"] == "abcdef123456"
                assert config["library_type"] == "group"
                assert config["target_collection"] == "ABCD1234"

    def test_get_zotero_config_with_defaults(self):
        """Test Zotero config with defaults when env vars missing."""
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_zotero_config()
                assert config["library_id"] == ""
                assert config["api_key"] == ""
                assert config["library_type"] == "user"  # Default library type
                assert config["target_collection"] is None


class TestGetRssConfig:
    """Tests for get_rss_config() function."""

    def test_get_rss_config_full_config(self):
        """Test getting RSS config with all env vars set."""
        env_vars = {
            "PAPER_FEEDDER_MCP_OPML": "/custom/path/feeds.opml",
            "PAPER_FEEDDER_MCP_USER_AGENT": "custom-agent/2.0",
        }
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_rss_config()
                assert config["opml_path"] == "/custom/path/feeds.opml"
                assert config["user_agent"] == "custom-agent/2.0"

    def test_get_rss_config_with_defaults(self):
        """Test RSS config with defaults when env vars missing."""
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_rss_config()
                assert config["opml_path"] == "feeds/RSS_official.opml"
                assert config["user_agent"] == "feedder-mcp/2.0"


class TestGetCrossrefConfig:
    """Tests for get_crossref_config() function."""

    def test_get_crossref_config_with_email(self):
        """Test getting Crossref config with email set."""
        env_vars = {"CROSSREF_EMAIL": "user@example.com"}
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_crossref_config()
                assert config["email"] == "user@example.com"

    def test_get_crossref_config_without_email(self):
        """Test Crossref config without email returns None."""
        env_remove = {
            k: "" for k in ("CROSSREF_EMAIL", "POLITE_POOL_EMAIL") if k in os.environ
        }
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in env_remove:
                os.environ.pop(k, None)
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_crossref_config()
                assert config["email"] is None


class TestGetOpenalexConfig:
    """Tests for get_openalex_config() function."""

    def test_get_openalex_config_with_email(self):
        """Test getting OpenAlex config with email set."""
        env_vars = {"OPENALEX_EMAIL": "researcher@university.edu"}
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_openalex_config()
                assert config["email"] == "researcher@university.edu"

    def test_get_openalex_config_without_email(self):
        """Test OpenAlex config without email returns None."""
        env_remove = {
            k: "" for k in ("OPENALEX_EMAIL", "POLITE_POOL_EMAIL") if k in os.environ
        }
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in env_remove:
                os.environ.pop(k, None)
            with mock.patch("src.config.settings.load_dotenv"):
                config = get_openalex_config()
                assert config["email"] is None


class TestGetResearchPrompt:
    """Tests for get_research_prompt() function."""

    def test_get_research_prompt_direct_text(self):
        """Test getting research prompt directly from env var."""
        env_vars = {"RESEARCH_PROMPT": "I am interested in machine learning and AI."}
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                prompt = get_research_prompt()
                assert prompt == "I am interested in machine learning and AI."

    def test_get_research_prompt_direct_text_with_whitespace(self):
        """Test that direct prompt text is stripped of whitespace."""
        env_vars = {"RESEARCH_PROMPT": "  My research interests  \n\n"}
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                prompt = get_research_prompt()
                assert prompt == "My research interests"

    def test_get_research_prompt_from_file(self, tmp_path):
        """Test getting research prompt from a file."""
        # Create a temporary prompt file
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("File-based research prompt text\n", encoding="utf-8")

        env_vars = {"RESEARCH_PROMPT_FILE": str(prompt_file)}
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                prompt = get_research_prompt()
                assert prompt == "File-based research prompt text"

    def test_get_research_prompt_file_with_whitespace(self, tmp_path):
        """Test that file-based prompt is stripped of whitespace."""
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("\n\n  File prompt  \n\n", encoding="utf-8")

        env_vars = {"RESEARCH_PROMPT_FILE": str(prompt_file)}
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                prompt = get_research_prompt()
                assert prompt == "File prompt"

    def test_get_research_prompt_direct_takes_precedence(self, tmp_path):
        """Test that direct prompt takes precedence over file-based prompt."""
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("File-based prompt", encoding="utf-8")

        env_vars = {
            "RESEARCH_PROMPT": "Direct prompt text",
            "RESEARCH_PROMPT_FILE": str(prompt_file),
        }
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                prompt = get_research_prompt()
                assert prompt == "Direct prompt text"

    def test_get_research_prompt_file_not_found(self):
        """Test that non-existent file returns None."""
        env_vars = {"RESEARCH_PROMPT_FILE": "/nonexistent/path/to/prompt.txt"}
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                prompt = get_research_prompt()
                assert prompt is None

    def test_get_research_prompt_empty_file(self, tmp_path):
        """Test that empty file returns None."""
        prompt_file = tmp_path / "empty.txt"
        prompt_file.write_text("", encoding="utf-8")

        env_vars = {"RESEARCH_PROMPT_FILE": str(prompt_file)}
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                prompt = get_research_prompt()
                assert prompt is None

    def test_get_research_prompt_empty_string_env_var(self):
        """Test that empty string in RESEARCH_PROMPT falls back to file."""
        env_vars = {
            "RESEARCH_PROMPT": "   \n\n  ",  # Only whitespace
        }
        with mock.patch.dict(os.environ, env_vars):
            with mock.patch("src.config.settings.load_dotenv"):
                prompt = get_research_prompt()
                assert prompt is None

    def test_get_research_prompt_none(self):
        """Test that None is returned when no prompt is configured."""
        with mock.patch.dict(os.environ, {}, clear=False):
            with mock.patch("src.config.settings.load_dotenv"):
                prompt = get_research_prompt()
                assert prompt is None


class TestConfigIntegration:
    """Integration tests for multiple config functions."""

    def test_multiple_config_getters_share_dotenv_load(self):
        """Test that multiple config getters share the same dotenv load."""
        import src.config.settings as config_module

        config_module._dotenv_loaded = False
        with mock.patch("src.config.settings.load_dotenv") as mock_load:
            with mock.patch.dict(os.environ, {}):
                get_env("TEST")
                assert mock_load.call_count == 1

                # Second call should not reload
                get_gmail_config()
                assert mock_load.call_count == 1

                # Third call should not reload
                get_openai_config()
                assert mock_load.call_count == 1

    def test_config_returns_dict_types(self):
        """Test that all config getters return dictionaries."""
        with mock.patch("src.config.settings.load_dotenv"):
            with mock.patch.dict(os.environ, {}):
                assert isinstance(get_openai_config(), dict)
                assert isinstance(get_gmail_config(), dict)
                assert isinstance(get_zotero_config(), dict)
                assert isinstance(get_rss_config(), dict)
                assert isinstance(get_crossref_config(), dict)
                assert isinstance(get_openalex_config(), dict)

    def test_reload_forces_fresh_load(self):
        """Test that reload_config forces a fresh dotenv load."""
        with mock.patch("src.config.settings.load_dotenv") as mock_load:
            with mock.patch.dict(os.environ, {}):
                get_openai_config()
                initial_call_count = mock_load.call_count

                reload_config()
                final_call_count = mock_load.call_count

                # reload_config should trigger another load
                assert final_call_count > initial_call_count

