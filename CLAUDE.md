# CLAUDE.md - Developer Guide for Claude Code

This file provides guidance for Claude Code instances working in the `paper-feed` repository.

## Project Overview

**paper-feed** is a Python framework for collecting, filtering, and exporting academic papers from RSS feeds and email alerts. It uses an async-first architecture with abstract base classes for extensibility.

- **Language**: Python 3.10+
- **Package Manager**: `uv` (NOT pip)
- **Testing**: pytest with pytest-asyncio (auto mode)
- **CLI**: argparse with bilingual help (English | 中文)
- **Data Models**: Pydantic v2

## Development Commands

### Setup and Installation
```bash
# Install dependencies
uv sync

# Install with all optional dependencies
uv sync --all-extras

# Install in development mode
uv pip install -e .
```

### Testing
```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_models.py

# Run with coverage
uv run pytest --cov=paper_feed --cov-report=html

# Run with verbose output
uv run pytest -v
```

### Code Quality
```bash
# Format code with ruff
uv run ruff format .

# Lint code
uv run ruff check .

# Fix auto-fixable issues
uv run ruff check --fix .

# Type checking (if mypy is configured)
uv run mypy src/paper_feed
```

### CLI Usage
```bash
# Show help
uv run paper-feed --help
uv run paper-feed fetch --help

# Fetch papers from RSS
uv run paper-feed fetch -s rss -o papers.json

# Filter papers
uv run paper-feed filter -i papers.json -o filtered.json -k "machine learning" "neural network"

# Enrich with metadata
uv run paper-feed enrich -i filtered.json -o enriched.json

# Export to JSON
uv run paper-feed export -i enriched.json -f json -o final.json
```

## Architecture

### Core Components

1. **Data Model** (`src/paper_feed/core/models.py`)
   - `PaperItem`: Central Pydantic model for all paper data
   - `FilterCriteria`: Filter configuration (keywords use OR logic, not AND)
   - `FilterResult`: Results from filtering pipeline

2. **Abstract Base Classes** (`src/paper_feed/core/base.py`)
   - `PaperSource`: Base for all data sources (RSS, Gmail, etc.)
   - `ExportAdapter`: Base for all export formats (JSON, Zotero, etc.)

3. **Two-Stage Filtering Pipeline** (`src/paper_feed/filters/`)
   - **Stage 1**: `KeywordFilterStage` - Fast keyword matching (OR logic, broad)
   - **Stage 2**: `AIFilterStage` - LLM-based semantic relevance (precise)
   - `FilterPipeline`: Orchestrates both stages

4. **CLI** (`src/paper_feed/core/cli.py`)
   - Four main commands: `fetch`, `filter`, `enrich`, `export`
   - Bilingual help text (English | 中文)
   - Short options (-i, -o, -s, -k, etc.) and aliases for convenience

### Design Patterns

1. **Abstract Base Class Pattern**
   ```python
   from paper_feed.core.base import PaperSource

   class MySource(PaperSource):
       async def fetch_papers(self, limit: int | None = None, since: date | None = None) -> list[PaperItem]:
           # Implementation here
           pass
   ```

2. **Optional Dependencies with Guards**
   ```python
   try:
       from openai import OpenAI
       HAS_OPENAI = True
   except ImportError:
       HAS_OPENAI = False

   # Later in code:
   if not HAS_OPENAI:
       raise ImportError("OpenAI package required. Install with: uv sync --extra openai")
   ```

3. **Async-First Design**
   - All I/O operations are async (HTTP requests, file operations)
   - Use `asyncio.Semaphore` for concurrency control
   - Use `asyncio.gather()` for parallel operations
   - CLI handlers are async functions called via `asyncio.run()`

4. **Configuration via Environment Variables**
   ```python
   from paper_feed.core.config import get_openai_config, get_zotero_config

   # Loads from environment variables or .env file
   config = get_openai_config()
   api_key = config.get("api_key")
   ```

## Key Architectural Constraints

**CRITICAL**: These rules MUST be followed when modifying code:

1. **Use `uv`, not `pip`** for all package operations
2. **FilterCriteria keywords use OR logic**, not AND (despite what intuition might suggest)
3. **All test functions are automatically async** - DO NOT add `@pytest.mark.asyncio` decorator
4. **Abstract base classes MUST be extended**, not modified directly
5. **PaperItem is the single source of truth** - don't create alternative data structures
6. **CLI help MUST be bilingual** - format: `"English text | 中文文本"`
7. **Optional dependencies MUST have import guards** - raise clear error messages if missing
8. **Never use `asyncio.run()` inside async functions** - only in sync entry points

## Development Workflow Rules

**CRITICAL**: These workflow rules MUST be followed when working on this project:

1. **Describe your approach before writing any code and wait for approval**
   - Before implementing any feature or fix, clearly describe your proposed solution
   - If requirements are unclear, ask clarifying questions BEFORE writing code
   - Wait for user confirmation before proceeding with implementation
   - This prevents wasted effort and ensures alignment with project goals

2. **Break down large changes into smaller tasks**
   - If a task requires modifying more than 3 files, STOP and break it down
   - Create smaller, focused sub-tasks that can be completed independently
   - This makes code review easier and reduces the risk of introducing bugs
   - Each sub-task should have a clear, testable outcome

3. **List potential issues and suggest test cases after writing code**
   - After implementing any feature, proactively identify potential edge cases
   - List possible failure scenarios and error conditions
   - Suggest specific test cases to cover these issues
   - This helps ensure comprehensive test coverage and prevents regressions

4. **Write a failing test before fixing a bug**
   - When a bug is discovered, first write a test that reproduces the bug
   - The test should fail initially (confirming the bug exists)
   - Then fix the bug until the test passes
   - This prevents regression and ensures the bug is truly fixed
   - Keep the test in the test suite to prevent future regressions

5. **Add new rules to CLAUDE.md when corrected**
   - Every time the user corrects a mistake or provides guidance
   - Add a new rule to this file (CLAUDE.md) to prevent recurrence
   - This creates a growing knowledge base of project-specific practices
   - Future Claude Code instances will benefit from these lessons learned
   - Update the "Last Updated" date at the bottom of this file

## Configuration System

Configuration is loaded from environment variables and `.env` files:

- **RSS Source**: `RSS_OPML_PATH`
- **Gmail Source**: `GMAIL_CREDENTIALS_PATH`, `GMAIL_TOKEN_PATH`
- **OpenAI**: `OPENAI_API_KEY`, `OPENAI_BASE_URL` (optional)
- **Zotero**: `ZOTERO_LIBRARY_ID`, `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_TYPE`

See `src/paper_feed/core/config.py` for details.

## Testing Strategy

### Test Organization
```
tests/
├── test_models.py          # Data model tests
├── test_filters.py         # Filter pipeline tests
├── sources/
│   ├── test_rss.py        # RSS source tests
│   └── test_gmail.py      # Gmail source tests
└── adapters/
    ├── test_json.py       # JSON export tests
    └── test_zotero.py     # Zotero export tests
```

### Key Testing Patterns

1. **Async Tests** (auto mode enabled)
   ```python
   # NO @pytest.mark.asyncio needed
   async def test_fetch_papers():
       source = RSSSource("test.opml")
       papers = await source.fetch_papers()
       assert len(papers) > 0
   ```

2. **Mocking HTTP Requests**
   ```python
   import httpx
   from unittest.mock import AsyncMock, patch

   @patch('httpx.AsyncClient.get')
   async def test_api_call(mock_get):
       mock_get.return_value = AsyncMock(json=lambda: {"title": "Test"})
       # Test implementation
   ```

3. **Fixtures for Test Data**
   ```python
   @pytest.fixture
   def sample_papers():
       return [
           PaperItem(title="Paper 1", url="http://example.com/1"),
           PaperItem(title="Paper 2", url="http://example.com/2"),
       ]
   ```

### Running Tests

- **350+ tests** in total - all must pass before committing
- Use `uv run pytest` (not `pytest` directly)
- Coverage target: >80% for core modules

## CLI Design Patterns

### Parameter Naming Convention

1. **Short options** (-s, -i, -o, -k, -x, -a, -f, -m, -j, -n, -q)
2. **Primary long options** (--source, --input, --output, --keywords)
3. **Aliases for clarity** (--max-papers, --from-date, --gmail-query)
4. **Consistent dest names** for argument access

Example:
```python
parser.add_argument(
    "-n", "--limit", "--max-papers",
    dest="limit",
    type=int,
    help="Maximum number of papers to fetch | 最大论文获取数量",
)
```

### Bilingual Help Text

Format: `"English description | 中文说明"`

Always provide both languages for:
- Command descriptions
- Argument help text
- Choice values (where appropriate)

## Common Workflows

### 1. Adding a New Data Source

```python
# 1. Create new file: src/paper_feed/sources/my_source.py
from paper_feed.core.base import PaperSource
from paper_feed.core.models import PaperItem

class MySource(PaperSource):
    async def fetch_papers(self, limit: int | None = None, since: date | None = None) -> list[PaperItem]:
        # Implementation
        papers = []
        # ... fetch logic ...
        return papers

# 2. Add CLI handler in src/paper_feed/core/cli.py
# Add to _handle_fetch() function:
elif args.source == "my_source":
    from paper_feed.sources.my_source import MySource
    source = MySource()
    papers = await source.fetch_papers(limit=args.limit, since=since)

# 3. Update CLI choices in _build_parser()
fetch_parser.add_argument(
    "-s", "--source",
    choices=["rss", "gmail", "my_source"],  # Add here
    default="rss",
    help="Data source | 数据源",
)

# 4. Write tests in tests/sources/test_my_source.py
async def test_my_source_fetch():
    source = MySource()
    papers = await source.fetch_papers(limit=10)
    assert len(papers) <= 10
    assert all(isinstance(p, PaperItem) for p in papers)
```

### 2. Adding a New Filter Stage

```python
# 1. Create new file: src/paper_feed/filters/my_filter.py
from paper_feed.core.models import PaperItem, FilterCriteria

class MyFilterStage:
    async def filter(self, papers: list[PaperItem], criteria: FilterCriteria) -> list[PaperItem]:
        # Implementation
        filtered = []
        for paper in papers:
            if self._should_include(paper, criteria):
                filtered.append(paper)
        return filtered

    def _should_include(self, paper: PaperItem, criteria: FilterCriteria) -> bool:
        # Filter logic
        return True

# 2. Add to FilterPipeline in src/paper_feed/filters/pipeline.py
from paper_feed.filters.my_filter import MyFilterStage

class FilterPipeline:
    def __init__(self, llm_client=None):
        self.stages = [
            KeywordFilterStage(),
            MyFilterStage(),  # Add here
            AIFilterStage(llm_client) if llm_client else None,
        ]
        self.stages = [s for s in self.stages if s is not None]

# 3. Write tests in tests/test_filters.py
async def test_my_filter_stage():
    stage = MyFilterStage()
    papers = [PaperItem(title="Test", url="http://example.com")]
    criteria = FilterCriteria(keywords=["test"])
    result = await stage.filter(papers, criteria)
    assert len(result) >= 0
```

### 3. Adding a New Export Format

```python
# 1. Create new file: src/paper_feed/adapters/my_format.py
from paper_feed.core.base import ExportAdapter
from paper_feed.core.models import PaperItem

class MyFormatAdapter(ExportAdapter):
    async def export(self, papers: list[PaperItem], output_path: str, **kwargs) -> None:
        # Implementation
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write papers in your format
            pass

# 2. Add CLI handler in src/paper_feed/core/cli.py
# Add to _handle_export() function:
elif args.format == "my_format":
    from paper_feed.adapters.my_format import MyFormatAdapter
    adapter = MyFormatAdapter()
    await adapter.export(papers, args.output)

# 3. Update CLI choices in _build_parser()
export_parser.add_argument(
    "-f", "--format",
    choices=["json", "zotero", "my_format"],  # Add here
    default="json",
    help="Export format | 导出格式",
)

# 4. Write tests in tests/adapters/test_my_format.py
async def test_my_format_export():
    adapter = MyFormatAdapter()
    papers = [PaperItem(title="Test", url="http://example.com")]
    await adapter.export(papers, "/tmp/test.out")
    assert Path("/tmp/test.out").exists()
```

## Important Gotchas

### 1. FilterCriteria Keywords Logic
**CRITICAL**: `FilterCriteria.keywords` uses **OR logic**, not AND logic.

```python
# This matches papers with "machine learning" OR "neural network"
criteria = FilterCriteria(keywords=["machine learning", "neural network"])
```

### 2. Async Test Auto-Detection
pytest-asyncio is configured with `asyncio_mode = auto` in `pyproject.toml`. This means:

```python
# ✅ CORRECT - no decorator needed
async def test_something():
    result = await async_function()
    assert result is not None

# ❌ WRONG - don't add decorator
@pytest.mark.asyncio  # Not needed!
async def test_something():
    pass
```

### 3. Optional Dependencies
Always guard imports for optional dependencies:

```python
# ✅ CORRECT
try:
    from openai import OpenAI
except ImportError:
    raise ImportError("OpenAI required. Install: uv sync --extra openai")

# ❌ WRONG - crashes if package not installed
from openai import OpenAI  # No guard
```

### 4. CLI Argument Destinations
Use `dest` parameter to avoid conflicts with aliases:

```python
# ✅ CORRECT
parser.add_argument("--limit", "--max-papers", dest="limit")
# Access via: args.limit

# ❌ WRONG - creates ambiguity
parser.add_argument("--limit", "--max-papers")
# Which attribute? args.limit or args.max_papers?
```

### 5. JSON Serialization with Pydantic
Use `model_dump()` (Pydantic v2), not `dict()`:

```python
# ✅ CORRECT (Pydantic v2)
data = [p.model_dump() for p in papers]

# ❌ WRONG (Pydantic v1)
data = [p.dict() for p in papers]  # Deprecated
```

### 6. File Path Handling
Always use `pathlib.Path` for cross-platform compatibility:

```python
# ✅ CORRECT
from pathlib import Path
filepath = Path(args.output)
filepath.parent.mkdir(parents=True, exist_ok=True)

# ❌ WRONG - platform-specific
import os
os.makedirs(os.path.dirname(args.output))  # Fails if dir exists
```

### 7. Async Context Managers
Always close async HTTP clients:

```python
# ✅ CORRECT
async with httpx.AsyncClient() as client:
    response = await client.get(url)

# Or manually:
client = httpx.AsyncClient()
try:
    response = await client.get(url)
finally:
    await client.aclose()

# ❌ WRONG - resource leak
client = httpx.AsyncClient()
response = await client.get(url)  # Never closed
```

## Version Notes

- **v1.0.0**: Initial release
- **v1.1.0**: Added short CLI options, parameter aliases, Chinese help text
- Python 3.10+ required (uses `| None` union syntax, not `Optional[]`)
- Pydantic v2 API (`model_dump()`, `model_validate()`)
- pytest-asyncio auto mode (no decorators needed)

## Quick Reference

### Package Management
- Install: `uv sync`
- Add dependency: `uv add package-name`
- Add dev dependency: `uv add --dev package-name`
- Add optional dependency: edit `pyproject.toml` [project.optional-dependencies]

### Testing
- Run all: `uv run pytest`
- Run one: `uv run pytest tests/test_models.py::test_paper_item_creation`
- With coverage: `uv run pytest --cov=paper_feed`
- Verbose: `uv run pytest -v`

### Code Quality
- Format: `uv run ruff format .`
- Lint: `uv run ruff check .`
- Fix: `uv run ruff check --fix .`

### Git Workflow
- Current branch: `master`
- Main branch: `main` (use for PRs)
- Always test before committing: `uv run pytest`
- Always format before committing: `uv run ruff format .`

## Documentation Files

- `README.md`: English project overview and quick start
- `中文指南.md`: Comprehensive Chinese guide (1055 lines)
- `测试结果.md`: Complete workflow test results (719 lines)
- `CLI参数快速参考.md`: CLI parameter reference
- `CLI中文帮助说明.md`: Chinese CLI help documentation
- `最终更新总结.md`: Summary of all v1.1.0 updates

## Getting Help

- Run `uv run paper-feed --help` for CLI help
- Read `中文指南.md` for detailed Chinese documentation
- Read `README.md` for English overview
- Check `tests/` directory for usage examples
- Review `src/paper_feed/core/models.py` for data structures

---

**Last Updated**: 2026-02-07
**Framework Version**: v1.1.0
**Python Version**: 3.10+
