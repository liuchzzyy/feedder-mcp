# CLAUDE.md - Developer Guide for feedder-mcp

This file provides guidance for contributors working in the `feedder-mcp` repository.

## Project Overview

**feedder-mcp** is an MCP server and CLI for collecting, filtering, enriching, and exporting academic papers from RSS feeds and Gmail alerts.

- **Language**: Python 3.12+
- **Package Manager**: `uv`
- **Testing**: pytest + pytest-asyncio (auto mode)
- **CLI**: argparse
- **Data Models**: Pydantic v2 + pydantic-settings
- **MCP Server**: `mcp` stdio server
- **Zotero Export**: local `zotero-mcp` repository (set `ZOTERO_MCP_PATH` if needed)

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

- `src/server.py`: MCP server entry (stdio)
- `src/client/cli.py`: CLI entry (serve default + subcommands)
- `src/config/`: settings (pydantic-settings)
- `src/handlers/`: MCP tools and prompts
- `src/models/`: schemas and core data models
- `src/services/`: fetch/filter/enrich/export services
- `src/sources/`: RSS, Gmail, CrossRef, OpenAlex
- `src/filters/`: keyword + AI filter pipeline
- `src/ai/`: keyword generator
- `src/adapters/`: JSON, Zotero
- `src/utils/`: shared helpers and errors

## Key Constraints

1. Preserve the layered architecture (handlers -> services -> sources/filters/adapters).
2. `FilterCriteria.keywords` uses **OR logic**.
3. All I/O is async; use `asyncio.to_thread()` for sync libraries.
4. Optional dependencies must be guarded with `try/except ImportError`.
5. MCP tools should return JSON-serializable outputs.
6. Use `feedder-mcp delete` to clean `output/` and common intermediate files when needed.

## Configuration (selected)

- **Server**: `SERVER_NAME`
- **RSS**: `PAPER_FEEDDER_MCP_OPML`, `RSS_TIMEOUT`, `RSS_MAX_CONCURRENT`
- **User-Agent**: `PAPER_FEEDDER_MCP_USER_AGENT`
- **Gmail**:
  - Credentials: `GMAIL_TOKEN_FILE`, `GMAIL_CREDENTIALS_FILE` (defaults to `feeds/`)
  - Optional inline JSON: `GMAIL_TOKEN_JSON`, `GMAIL_CREDENTIALS_JSON`
  - Sender controls: `GMAIL_SENDER_FILTER` (allowlist), `GMAIL_SENDER_MAP_JSON` (email -> source)
  - Processing: `GMAIL_TRASH_AFTER_PROCESS`, `GMAIL_VERIFY_TRASH_AFTER_PROCESS`
- **AI**: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `RESEARCH_PROMPT`
- **Zotero**: `ZOTERO_LIBRARY_ID`, `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_TYPE`, `ZOTERO_MCP_PATH`

## Notes

- Do not commit sensitive files (tokens/credentials).
- Keep documentation (`README.md`, `doc/中文指南.md`) in sync with code changes.
- Use `feedder-mcp delete` to clean pipeline outputs when needed.
- `enrich` accepts `--api/--source/--provider` and `--jobs/--concurrency/--parallel`.

---

**Version**: 2.5.0
**Last Updated**: 2026-02-12

