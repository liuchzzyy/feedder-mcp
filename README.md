# feedder-mcp

An MCP (Model Context Protocol) server for collecting, filtering, enriching, and exporting academic papers from RSS feeds and Gmail alerts.

Version: 2.5.1.r2 (2026-02-24)

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
cd feedder-mcp
uv sync

# With development tools (pytest, ruff, ty)
uv sync --group dev
```

## Quick Start

### MCP Server (stdio)

```bash
# Default: serve over stdio
feedder-mcp

# Explicit serve
feedder-mcp serve

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
feedder-mcp fetch --source rss --limit 200 --output output/fetched_papers.json

# 2. Keyword filter (OR logic)
feedder-mcp filter --input output/fetched_papers.json --output output/filtered_papers.json \
    --keywords battery zinc electrolyte operando

# 3. Semantic filter (default enabled; requires OPENAI_API_KEY in .env)
feedder-mcp filter --input output/filtered_papers.json --output output/semantic_filtered_papers.json \
    --keywords battery zinc

# 4. Enrich with CrossRef + OpenAlex metadata
feedder-mcp enrich --input output/semantic_filtered_papers.json --output output/enriched_papers.json --api all --concurrency 5

# 5. Export (metadata included by default)
feedder-mcp export --input output/enriched_papers.json --output output/exported_papers.json --format json

# 6. Optional cleanup
feedder-mcp delete
```

Notes:
- Use `feedder-mcp delete` to clean `output/` and common intermediate files when needed.
- Use `--no-semantic-filter` (or old alias `--no-ai`) to disable semantic filtering; use `--no-metadata` to omit extra fields in export.
- If `--keywords` is omitted, keywords will be auto-generated from `RESEARCH_PROMPT` using the AI keyword generator.
- If keyword auto-generation fails and returns empty keywords, `filter` now exits with an error instead of silently passing all papers.
- If OpenAlex returns `429`, set `OPENALEX_API_KEY`, lower `OPENALEX_MAX_REQUESTS_PER_SECOND`, and consider reducing `--concurrency`.
- For Zotero exports, use `--collection <key>` or set `TARGET_COLLECTION` in `.env`/GitHub Secrets.

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

    await JSONAdapter().export(result.papers, "output/exported_papers.json", include_metadata=True)

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
| `TARGET_COLLECTION` | Default Zotero collection key used by `export --format zotero` |
| `ZOTERO_MCP_PATH` | Path to `zotero-mcp/src` (if not at default location) |

See `.env.example` for all available options.

## GitHub Actions

Workflow: `.github/workflows/RSS+GMAIL.yml`

- Trigger:
  - Scheduled daily run
  - Manual run (`workflow_dispatch`)
- Pipeline:
  - RSS: `fetch -> filter(--no-semantic-filter) -> filter(--semantic-filter) -> enrich -> export`
  - Gmail: `fetch -> filter(--no-semantic-filter) -> filter(--semantic-filter) -> enrich -> export`
- Behavior:
  - If fetched count is `0`, downstream steps are skipped safely for that source.
  - If `TARGET_COLLECTION` is set, Zotero export writes into that collection.

Recommended repository secrets:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL` (optional)
- `OPENAI_MODEL` (optional)
- `RESEARCH_PROMPT` (recommended)
- `OPENALEX_API_KEY` (recommended)
- `POLITE_POOL_EMAIL` (recommended)
- `GMAIL_TOKEN_JSON` / `GMAIL_CREDENTIALS_JSON` (for Gmail pipeline)
- `GMAIL_SENDER_FILTER` / `GMAIL_SENDER_MAP_JSON` (optional)
- `ZOTERO_LIBRARY_ID`
- `ZOTERO_API_KEY`
- `TARGET_COLLECTION` (optional)

## Project Structure

```
feedder-mcp/
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

