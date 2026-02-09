# paper-feedder-mcp

An MCP (Model Context Protocol) server for collecting, filtering, enriching, and exporting academic papers from RSS feeds and Gmail alerts.

Version: 2.1.1 (2026-02-09)

## Features

- MCP server with tools for fetch, filter, enrich, export, and keyword generation
- RSS feed ingestion with OPML support, concurrency, and deduplication
- Gmail alert ingestion via EZGmail (optional)
- Two-stage filtering: AI-generated keywords + AI semantic pass (default on)
- Metadata enrichment via CrossRef and OpenAlex
- Export adapters for JSON and Zotero (via local `zotero-mcp` repo)
- CLI utilities for direct operations

## Requirements

- Python 3.12+
- uv (package manager)

## Installation

```bash
cd paper-feedder-mcp
uv sync

# With development tools (pytest, ruff, ty)
uv sync --group dev
```

## Quick Start

### MCP Server (stdio)

```bash
# Default: serve over stdio
paper-feedder-mcp

# Explicit serve
paper-feedder-mcp serve

# Or via module
python -m src
```

### MCP Tool Output

All MCP tools return JSON in a consistent envelope:

```json
{
  "ok": true,
  "data": {
    "...": "..."
  },
  "meta": {
    "...": "..."
  }
}
```

On errors:

```json
{
  "ok": false,
  "error": "ErrorType: message"
}
```

### CLI Pipeline

```bash
# 1. Fetch papers from RSS feeds (default --since: last 15 days)
paper-feedder-mcp fetch --source rss --limit 200 --output output/raw.json

# 2. Keyword filter (OR logic)
paper-feedder-mcp filter --input output/raw.json --output output/filtered.json \
    --keywords battery zinc electrolyte operando

# 3. AI semantic filter (default enabled; requires OPENAI_API_KEY in .env)
paper-feedder-mcp filter --input output/filtered.json --output output/ai_filtered.json \
    --keywords battery zinc

# 4. Enrich with CrossRef + OpenAlex metadata
paper-feedder-mcp enrich --input output/ai_filtered.json --output output/enriched.json --api all --concurrency 5

# 5. Export (metadata included by default)
paper-feedder-mcp export --input output/enriched.json --output output/final.json --format json

# 6. Optional cleanup
paper-feedder-mcp delete
```

Notes:
- Use `paper-feedder-mcp delete` to clean `output/` and common intermediate files when needed.
- Use `--no-ai` to disable AI filtering; use `--no-metadata` to omit extra fields in export.
- If `--keywords` is omitted, keywords will be auto-generated from `RESEARCH_PROMPT` using the AI keyword generator.
- If OpenAlex returns `429`, set `OPENALEX_API_KEY`, lower `OPENALEX_MAX_REQUESTS_PER_SECOND`, and consider reducing `--concurrency`.

### Python API

```python
import asyncio
from src.sources import RSSSource
from src.filters import FilterPipeline
from src.adapters import JSONAdapter
from src.models.responses import FilterCriteria

async def main():
    source = RSSSource("feeds/RSS_official.opml")
    papers = await source.fetch_papers(limit=50)

    criteria = FilterCriteria(keywords=["battery", "electrode"])
    result = await FilterPipeline().filter(papers, criteria)

    await JSONAdapter().export(result.papers, "output/papers.json", include_metadata=True)

asyncio.run(main())
```

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Key settings:

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | API key for AI filtering (OpenAI-compatible) |
| `OPENAI_BASE_URL` | Custom API base URL |
| `RESEARCH_PROMPT` | Research interests for AI filtering |
| `GMAIL_TOKEN_JSON` | Gmail OAuth2 token (inline JSON) |
| `GMAIL_CREDENTIALS_JSON` | Gmail OAuth2 credentials (inline JSON) |
| `GMAIL_TOKEN_FILE` | Path to token file (default: `feeds/token.json`) |
| `GMAIL_CREDENTIALS_FILE` | Path to credentials file (default: `feeds/credentials.json`) |
| `GMAIL_TRASH_AFTER_PROCESS` | Move processed threads to Trash (default: `true`) |
| `GMAIL_VERIFY_TRASH_AFTER_PROCESS` | Verify Trash after processing (default: `true`) |
| `GMAIL_VERIFY_TRASH_LIMIT` | Max threads checked during Trash verification (default: `50`) |
| `GMAIL_SENDER_FILTER` | Comma-separated sender allowlist for Gmail filtering |
| `GMAIL_SENDER_MAP_JSON` | JSON map of sender email to source name |
| `POLITE_POOL_EMAIL` | Email for CrossRef/OpenAlex polite pool access |
| `PAPER_FEEDDER_MCP_OPML` | Path to OPML file with RSS feeds |
| `PAPER_FEEDDER_MCP_USER_AGENT` | Shared User-Agent for RSS/CrossRef/OpenAlex |
| `OPENALEX_API_KEY` | OpenAlex API key (recommended to avoid rate limits) |
| `OPENALEX_MAX_REQUESTS_PER_SECOND` | Client-side throttle for OpenAlex requests |
| `ZOTERO_MCP_PATH` | Path to `zotero-mcp/src` (if not at default location) |

See `.env.example` for all available options.

## Project Structure

```
paper-feedder-mcp/
├── src/
│   ├── server.py           # MCP server
│   ├── client/cli.py       # CLI entry
│   ├── config/             # Pydantic settings
│   ├── handlers/           # MCP tool/prompt handlers
│   ├── models/             # Schemas and data models
│   ├── services/           # Fetch/filter/enrich/export services
│   ├── sources/            # RSS, Gmail, CrossRef, OpenAlex
│   ├── filters/            # Keyword and AI filters
│   ├── adapters/           # JSON, Zotero export
│   ├── ai/                 # Keyword generator
│   └── utils/              # Text helpers and errors
├── tests/unit/
├── feeds/
├── doc/               # Documentation (中文指南.md)
└── pyproject.toml
```

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check .

# Type check
uv run ty check
```

## License

MIT
