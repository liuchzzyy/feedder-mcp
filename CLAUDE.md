# CLAUDE.md - Developer Guide for paper-feed

This file provides guidance for contributors working in the `paper-feed` repository.

## Project Overview

**paper-feed** is a Python framework for collecting, filtering, and exporting academic papers from RSS feeds and Gmail alerts. It uses an async-first architecture with extensible base classes.

- **Language**: Python 3.10+
- **Package Manager**: `uv`
- **Testing**: pytest + pytest-asyncio (auto mode)
- **CLI**: argparse with bilingual help (English | 中文)
- **Data Models**: Pydantic v2

## Development Commands

### Setup
```bash
uv sync
uv sync --group dev
```

### Testing
```bash
uv run pytest
uv run pytest tests/unit/test_gmail_source.py
uv run pytest -v
```

### Linting / Types
```bash
uv run ruff check .
uv run ty check
```

## Architecture

- **core/**: models, base classes, CLI, config
- **sources/**: RSS, Gmail, CrossRef, OpenAlex
- **filters/**: keyword + AI filter pipeline
- **adapters/**: JSON, Zotero
- **utils/**: shared text helpers

## Key Constraints

1. Preserve the layered architecture (core → sources/filters/adapters).
2. `FilterCriteria.keywords` uses **OR logic**.
3. All I/O is async; use `asyncio.to_thread()` for sync libraries.
4. Optional dependencies must be guarded with `try/except ImportError`.
5. CLI help text must remain bilingual.

## Configuration (selected)

- **RSS**: `PAPER_FEED_OPML`, `RSS_TIMEOUT`, `RSS_MAX_CONCURRENT`
- **Gmail**:
  - Credentials: `GMAIL_TOKEN_FILE`, `GMAIL_CREDENTIALS_FILE` (defaults to `feeds/`)
  - Optional inline JSON: `GMAIL_TOKEN_JSON`, `GMAIL_CREDENTIALS_JSON`
  - Sender controls: `GMAIL_SENDER_FILTER` (allowlist), `GMAIL_SENDER_MAP_JSON` (email → source)
  - Processing: `GMAIL_TRASH_AFTER_PROCESS`, `GMAIL_VERIFY_TRASH_AFTER_PROCESS`
- **AI**: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `RESEARCH_PROMPT`

## Notes

- Do not commit sensitive files (tokens/credentials).
- Keep documentation (`README.md`, `doc/中文指南.md`) in sync with code changes.

---

**Last Updated**: 2026-02-08
