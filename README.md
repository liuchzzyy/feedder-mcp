# paper-feed

**A modular Python framework for collecting, filtering, and exporting academic papers from RSS feeds and email alerts.**

paper-feed provides a clean, extensible architecture for building custom paper collection workflows. Fetch papers from arXiv, bioRxiv, Nature, and other sources, filter by keywords/categories/authors, and export to JSON or Zotero.

## Features

### Currently Implemented

- **RSS Feed Source**
  - Reads feeds from OPML files (arXiv, bioRxiv, Nature, Science, PNAS, ACS, etc.)
  - Concurrent fetching of all feeds with automatic deduplication
  - Auto-detects source name from URL
  - Configurable timeout, user-agent, and concurrency
  - Date-based filtering support

- **Keyword Filter Pipeline**
  - Filter by keywords (AND logic)
  - Filter by categories (OR logic)
  - Exclude by keywords
  - Filter by authors
  - Filter by publication date
  - Require PDF availability

- **Export Adapters**
  - **JSON Adapter**: Export to JSON with metadata
  - **Zotero Adapter**: Export to Zotero library (optional dependency)

### Planned Features

- Gmail alert parsing (Google Scholar, journal TOCs)
- AI-powered semantic filtering
- Additional export adapters (BibTeX, CSV, Markdown)

## Installation

### Quick Install (Local Development)

```bash
# Navigate to paper-feed directory
cd external/paper-feed

# Install in editable mode
pip install -e .
```

### With Optional Dependencies

```bash
# Install with Gmail support
pip install -e ".[gmail]"

# Install with LLM-based filtering
pip install -e ".[llm]"

# Install with development tools
pip install -e ".[dev]"

# Install everything
pip install -e ".[all]"
```

**Note:** Zotero adapter is planned for Phase 2 and not yet available.

### Prerequisites

- Python 3.10 or higher
- pip (Python package installer)

For detailed installation instructions, troubleshooting, and verification steps, see [docs/INSTALLATION.md](docs/INSTALLATION.md).

## Quick Start

Here's a complete workflow to fetch, filter, and export papers:

```python
import asyncio
from paper_feed import RSSSource, FilterPipeline, JSONAdapter, FilterCriteria

async def main():
    # Step 1: Fetch papers from all feeds in an OPML file
    source = RSSSource("feeds/RSS_official.opml")
    papers = await source.fetch_papers(limit=50)
    print(f"Fetched {len(papers)} papers from {source.feed_count} feeds")

    # Step 2: Filter by keywords
    criteria = FilterCriteria(
        keywords=["machine learning", "deep learning"],
        categories=["Computer Science"],
    )
    filtered = await FilterPipeline().filter(papers, criteria)
    print(f"Filtered to {filtered.passed_count} papers")

    # Step 3: Export to JSON
    await JSONAdapter().export(
        filtered.papers,
        "papers.json",
        include_metadata=True
    )
    print("Exported to papers.json")

if __name__ == "__main__":
    asyncio.run(main())
```

For more detailed tutorials and real-world examples, see [docs/QUICKSTART.md](docs/QUICKSTART.md).

## Usage Examples

### Example 1: Fetch from OPML File

```python
from paper_feed import RSSSource

# All feeds in the OPML are fetched concurrently
source = RSSSource("feeds/RSS_official.opml")
papers = await source.fetch_papers()
print(f"Fetched {len(papers)} papers from {source.feed_count} feeds")

# Inspect which feeds were loaded
for feed in source.feeds[:5]:
    print(f"  - {feed['title']}: {feed['url']}")
```

### Example 2: Advanced Filtering

```python
from paper_feed import FilterCriteria, FilterPipeline
from datetime import date

# Complex filter criteria
criteria = FilterCriteria(
    keywords=["neural networks", "transformers"],
    exclude_keywords=["review", "survey"],
    authors=["Hinton", "LeCun", "Bengio"],
    min_date=date(2023, 1, 1),
    has_pdf=True,
)

result = await FilterPipeline().filter(papers, criteria)
print(f"Found {result.passed_count} papers matching criteria")
```

### Example 3: Export with Custom Options

```python
from paper_feed import JSONAdapter

# Export without metadata (cleaner output)
await JSONAdapter().export(
    papers,
    "clean_papers.json",
    include_metadata=False
)

# Export with metadata (includes source-specific fields)
await JSONAdapter().export(
    papers,
    "full_papers.json",
    include_metadata=True
)
```

## Documentation

- **[Installation Guide](docs/INSTALLATION.md)** - Detailed setup instructions
- **[Quick Start Tutorial](docs/QUICKSTART.md)** - Complete workflow tutorial
- **[Architecture Overview](docs/ARCHITECTURE.md)** - Module structure and design patterns
- **[Adapter Documentation](docs/ADAPTERS.md)** - Export adapter details

## Examples

Check out the [examples/](examples/) directory for complete, runnable examples:

- **[complete_workflow.py](examples/complete_workflow.py)** - End-to-end workflow
- **[adapters_example.py](examples/adapters_example.py)** - Adapter usage examples

## Development

### Running Tests

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/unit/test_models.py -v
```

### Code Quality

```bash
# Lint code
ruff check

# Auto-fix issues
ruff check --fix

# Format code
ruff format
```

## Project Structure

```
paper-feed/
├── src/paper_feed/
│   ├── core/           # Core models and base classes
│   ├── sources/        # Data sources (RSS, Gmail)
│   ├── filters/        # Filter pipeline and stages
│   └── adapters/       # Export adapters (JSON, Zotero)
├── tests/              # Unit tests
├── docs/               # Documentation
├── examples/           # Usage examples
└── pyproject.toml      # Project configuration
```

For detailed architecture information, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Contributing

Contributions are welcome! Please see the main project's CONTRIBUTING.md for guidelines.

## License

MIT License - see LICENSE file for details.

## Roadmap

- [ ] Phase 1: Core functionality (RSS, filters, JSON export) ✅
- [ ] Phase 2: Zotero adapter implementation
- [ ] Phase 3: Gmail source integration
- [ ] Phase 4: AI-powered semantic filtering
- [ ] Phase 5: Additional export adapters (BibTeX, CSV, Markdown)
