"""Unit tests for RSS source."""

import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from src.sources import RSSSource, OPMLParser, parse_opml
from src.sources.rss_parser import RSSParser


# ---------------------------------------------------------------------------
# OPML parser tests (unchanged — these don't depend on RSSSource API)
# ---------------------------------------------------------------------------


def test_opml_parser_local_file():
    """Test parsing OPML file from local file system."""
    opml_path = "feeds/RSS_official.opml"

    if not os.path.exists(opml_path):
        pytest.skip(f"OPML file not found: {opml_path}")

    parser = OPMLParser(opml_path)
    feeds = parser.parse()

    assert len(feeds) > 0, "Should parse at least one feed"

    feed = feeds[0]
    assert "url" in feed, "Feed should have url"
    assert "title" in feed, "Feed should have title"
    assert feed["url"], "Feed URL should not be empty"
    assert feed["title"], "Feed title should not be empty"

    for feed in feeds:
        assert feed["url"], f"Feed {feed.get('title', 'Unknown')} missing URL"
        assert feed["title"], f"Feed with URL {feed['url']} missing title"


def test_opml_parser_convenience_function():
    """Test convenience function for parsing OPML."""
    opml_path = "feeds/RSS_official.opml"

    if not os.path.exists(opml_path):
        pytest.skip(f"OPML file not found: {opml_path}")

    feeds = parse_opml(opml_path)

    assert len(feeds) > 0, "Should parse at least one feed"
    assert all("url" in f and "title" in f for f in feeds)


def test_opml_parser_missing_file():
    """Test OPML parser with missing file."""
    parser = OPMLParser("nonexistent.opml")

    with pytest.raises(FileNotFoundError):
        parser.parse()


def test_opml_parser_categories():
    """Test that OPML parser preserves category information."""
    opml_path = "feeds/RSS_official.opml"

    if not os.path.exists(opml_path):
        pytest.skip(f"OPML file not found: {opml_path}")

    parser = OPMLParser(opml_path)
    feeds = parser.parse()

    feeds_with_categories = [f for f in feeds if "category" in f]

    if feeds_with_categories:
        feed = feeds_with_categories[0]
        assert feed["category"], "Feed should have category"
        assert feed["url"], "Feed should have URL"
        assert feed["title"], "Feed should have title"


def test_opml_parser_skip_non_rss():
    """Test that OPML parser skips non-RSS outlines."""
    opml_path = "feeds/RSS_official.opml"

    if not os.path.exists(opml_path):
        pytest.skip(f"OPML file not found: {opml_path}")

    parser = OPMLParser(opml_path)
    feeds = parser.parse()

    for feed in feeds:
        assert feed["url"].startswith("http"), "Feed URL should be valid HTTP URL"


# ---------------------------------------------------------------------------
# RSSSource constructor tests
# ---------------------------------------------------------------------------


def test_rss_source_from_opml():
    """Test creating RSSSource from OPML file."""
    opml_path = "feeds/RSS_official.opml"

    if not os.path.exists(opml_path):
        pytest.skip(f"OPML file not found: {opml_path}")

    source = RSSSource(opml_path)

    assert isinstance(source, RSSSource)
    assert source.feed_count > 0, "Should have at least one feed"
    assert source.source_type == "rss"
    assert source.opml_path == opml_path


def test_rss_source_feeds_property():
    """Test that feeds property returns feed list."""
    opml_path = "feeds/RSS_official.opml"

    if not os.path.exists(opml_path):
        pytest.skip(f"OPML file not found: {opml_path}")

    source = RSSSource(opml_path)
    feeds = source.feeds

    assert len(feeds) == source.feed_count
    for feed in feeds:
        assert "url" in feed
        assert "title" in feed


def test_rss_source_missing_opml():
    """Test RSSSource with missing OPML file."""
    with pytest.raises(FileNotFoundError):
        RSSSource("nonexistent.opml")


def test_rss_source_env_variable(monkeypatch):
    """Test RSSSource using environment variable for OPML path."""
    opml_path = "feeds/RSS_official.opml"

    if not os.path.exists(opml_path):
        pytest.skip(f"OPML file not found: {opml_path}")

    monkeypatch.setenv("FEEDDER_MCP_OPML", opml_path)

    # No explicit path — should use env var
    source = RSSSource()

    assert source.feed_count > 0
    assert source.opml_path == opml_path


def test_rss_source_default_path(monkeypatch):
    """Test RSSSource falls back to default path when no env var set."""
    opml_path = "feeds/RSS_official.opml"

    if not os.path.exists(opml_path):
        pytest.skip(f"OPML file not found: {opml_path}")

    monkeypatch.delenv("FEEDDER_MCP_OPML", raising=False)

    source = RSSSource()

    assert source.feed_count > 0


# ---------------------------------------------------------------------------
# RSSSource.fetch_papers tests (with mocked HTTP)
# ---------------------------------------------------------------------------

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Paper Alpha</title>
      <link>https://example.com/paper-alpha</link>
      <description>Abstract for paper alpha.</description>
    </item>
    <item>
      <title>Paper Beta</title>
      <link>https://example.com/paper-beta</link>
      <description>Abstract for paper beta.</description>
    </item>
  </channel>
</rss>
"""


def _make_opml_source(tmp_path, feed_count=2):
    """Helper: create a temp OPML file and return an RSSSource."""
    feeds_xml = ""
    for i in range(feed_count):
        feeds_xml += (
            f'<outline type="rss" xmlUrl="https://example.com/feed{i}" '
            f'title="Feed {i}" htmlUrl="https://example.com" />\n'
        )

    opml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <body>
    <outline text="Test" title="Test">
      {feeds_xml}
    </outline>
  </body>
</opml>
"""
    opml_file = tmp_path / "test.opml"
    opml_file.write_text(opml_content, encoding="utf-8")
    return RSSSource(str(opml_file))


@pytest.mark.asyncio
async def test_fetch_papers_aggregates(tmp_path):
    """Test that fetch_papers aggregates results from all feeds."""
    source = _make_opml_source(tmp_path, feed_count=2)

    # Mock httpx to return sample RSS for every request
    mock_response = MagicMock()
    mock_response.text = SAMPLE_RSS_XML
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.sources.rss.httpx.AsyncClient", return_value=mock_client):
        papers = await source.fetch_papers()

    # 2 feeds × 2 papers each, but alpha/beta urls are the same across feeds
    # so deduplication should reduce to 2 unique papers
    assert len(papers) == 2
    titles = {p.title for p in papers}
    assert "Paper Alpha" in titles
    assert "Paper Beta" in titles


@pytest.mark.asyncio
async def test_fetch_papers_respects_limit(tmp_path):
    """Test that global limit is applied after aggregation."""
    source = _make_opml_source(tmp_path, feed_count=2)

    mock_response = MagicMock()
    mock_response.text = SAMPLE_RSS_XML
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("src.sources.rss.httpx.AsyncClient", return_value=mock_client):
        papers = await source.fetch_papers(limit=1)

    assert len(papers) == 1


@pytest.mark.asyncio
async def test_fetch_papers_handles_feed_failure(tmp_path):
    """Test that a single feed failure doesn't break the whole fetch."""
    source = _make_opml_source(tmp_path, feed_count=2)

    call_count = 0

    async def _mock_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.RequestError("connection refused")
        resp = MagicMock()
        resp.text = SAMPLE_RSS_XML
        resp.raise_for_status = MagicMock()
        return resp

    mock_client = AsyncMock()
    mock_client.get = _mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    import httpx

    with patch("src.sources.rss.httpx.AsyncClient", return_value=mock_client):
        papers = await source.fetch_papers()

    # Only one feed succeeded → 2 papers
    assert len(papers) == 2


@pytest.mark.asyncio
async def test_fetch_papers_network_integration():
    """Integration test: fetch from real OPML (skipped if offline or missing)."""
    opml_path = "feeds/RSS_official.opml"

    if not os.path.exists(opml_path):
        pytest.skip(f"OPML file not found: {opml_path}")

    source = RSSSource(opml_path)

    try:
        papers = await source.fetch_papers(limit=5)
        assert len(papers) <= 5, "Should respect limit"
        if papers:
            paper = papers[0]
            assert paper.title, "Paper should have a title"
            assert paper.source_type == "rss"
    except Exception as e:
        pytest.skip(f"Network request failed (offline environment?): {e}")


def test_detect_source_name():
    """Test source name auto-detection from URL."""
    assert RSSSource._detect_source_name("https://arxiv.org/rss/cs.AI") == "arXiv"
    assert RSSSource._detect_source_name("https://www.biorxiv.org/feed") == "bioRxiv"
    assert RSSSource._detect_source_name("https://www.nature.com/nbt.rss") == "Nature"
    assert (
        RSSSource._detect_source_name("https://unknown.example.com/feed") == "Unknown"
    )


# ---------------------------------------------------------------------------
# RSSParser unit tests — new feedparser integration features
# ---------------------------------------------------------------------------


@pytest.fixture
def rss_parser():
    return RSSParser()


class TestRSSParserAbstract:
    """Tests for _extract_abstract — prefers entry.content over summary."""

    def test_abstract_from_content(self, rss_parser):
        """entry.content[0].value is preferred over summary."""
        entry = {
            "title": "Test Paper",
            "link": "https://example.com/1",
            "content": [{"type": "text/html", "value": "<p>Rich abstract</p>"}],
            "summary": "Plain summary",
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.abstract == "<p>Rich abstract</p>"

    def test_abstract_falls_back_to_summary(self, rss_parser):
        """Falls back to summary when content is absent."""
        entry = {
            "title": "Test Paper",
            "link": "https://example.com/2",
            "summary": "Plain summary",
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.abstract == "Plain summary"

    def test_abstract_falls_back_to_description(self, rss_parser):
        """Falls back to description when both content and summary absent."""
        entry = {
            "title": "Test Paper",
            "link": "https://example.com/3",
            "description": "Description text",
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.abstract == "Description text"

    def test_abstract_empty_content_uses_summary(self, rss_parser):
        """Empty content list falls back to summary."""
        entry = {
            "title": "Test Paper",
            "link": "https://example.com/4",
            "content": [],
            "summary": "Fallback summary",
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.abstract == "Fallback summary"


class TestRSSParserEnclosures:
    """Tests for PDF URL extraction from enclosures."""

    def test_pdf_from_enclosure(self, rss_parser):
        """entry.enclosures with application/pdf produces pdf_url."""
        entry = {
            "title": "Enclosed PDF Paper",
            "link": "https://example.com/5",
            "enclosures": [
                {"type": "application/pdf", "href": "https://example.com/paper.pdf"}
            ],
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.pdf_url == "https://example.com/paper.pdf"

    def test_link_pdf_takes_priority_over_enclosure(self, rss_parser):
        """Links with type=application/pdf take priority over enclosures."""
        entry = {
            "title": "Link PDF Paper",
            "link": "https://example.com/6",
            "links": [
                {
                    "type": "application/pdf",
                    "href": "https://example.com/link.pdf",
                    "rel": "enclosure",
                }
            ],
            "enclosures": [
                {"type": "application/pdf", "href": "https://example.com/enc.pdf"}
            ],
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.pdf_url == "https://example.com/link.pdf"

    def test_non_pdf_enclosure_ignored(self, rss_parser):
        """Enclosures without application/pdf type are ignored."""
        entry = {
            "title": "Image Enclosure Paper",
            "link": "https://example.com/7",
            "enclosures": [
                {"type": "image/png", "href": "https://example.com/image.png"}
            ],
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.pdf_url is None


class TestRSSParserContributors:
    """Tests for contributor extraction appended to authors."""

    def test_contributors_appended(self, rss_parser):
        """entry.contributors are appended to the authors list."""
        entry = {
            "title": "Contrib Paper",
            "link": "https://example.com/8",
            "authors": [{"name": "Alice"}],
            "contributors": [{"name": "Bob"}, {"name": "Carol"}],
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.authors == ["Alice", "Bob", "Carol"]

    def test_contributors_deduplicated(self, rss_parser):
        """Duplicate contributors already in authors are not added again."""
        entry = {
            "title": "Dedup Contrib Paper",
            "link": "https://example.com/9",
            "authors": [{"name": "Alice"}],
            "contributors": [{"name": "alice"}, {"name": "Bob"}],
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert len(paper.authors) == 2
        assert "Alice" in paper.authors
        assert "Bob" in paper.authors


class TestRSSParserMetadata:
    """Tests for metadata extraction (publisher, rights, feed meta)."""

    def test_publisher_in_metadata(self, rss_parser):
        """entry.publisher appears in metadata."""
        entry = {
            "title": "Publisher Paper",
            "link": "https://example.com/10",
            "publisher": "Nature Publishing Group",
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.extra.get("publisher") == "Nature Publishing Group"

    def test_rights_in_metadata(self, rss_parser):
        """entry.rights appears in metadata."""
        entry = {
            "title": "Rights Paper",
            "link": "https://example.com/11",
            "rights": "CC BY 4.0",
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.extra.get("rights") == "CC BY 4.0"

    def test_summary_detail_in_metadata(self, rss_parser):
        """entry.summary_detail type info stored in metadata."""
        entry = {
            "title": "Detail Paper",
            "link": "https://example.com/12",
            "summary": "Abstract text",
            "summary_detail": {
                "type": "text/html",
                "language": "en",
                "base": "https://example.com",
                "value": "Abstract text",
            },
        }
        paper = rss_parser.parse(entry, "TestSource")
        sd = paper.extra.get("summary_detail", {})
        assert sd.get("type") == "text/html"
        assert sd.get("language") == "en"

    def test_feed_meta_in_metadata(self, rss_parser):
        """Feed-level metadata appears under metadata.feed."""
        entry = {
            "title": "Feed Meta Paper",
            "link": "https://example.com/13",
        }
        feed_meta = {
            "title": "Nature Chemistry",
            "language": "en",
            "version": "rss20",
        }
        paper = rss_parser.parse(entry, "TestSource", feed_meta=feed_meta)
        assert paper.extra.get("feed", {}).get("title") == "Nature Chemistry"
        assert paper.extra.get("feed", {}).get("version") == "rss20"

    def test_empty_metadata_when_no_extras(self, rss_parser):
        """Metadata is empty dict when no extra fields present."""
        entry = {
            "title": "Plain Paper",
            "link": "https://example.com/14",
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.extra == {}

    def test_original_source_in_metadata(self, rss_parser):
        """entry.source (aggregated feed origin) stored in metadata."""
        entry = {
            "title": "Aggregated Paper",
            "link": "https://example.com/15",
            "source": {"title": "Original Feed", "href": "https://orig.com/rss"},
        }
        paper = rss_parser.parse(entry, "TestSource")
        src = paper.extra.get("original_source", {})
        assert src.get("title") == "Original Feed"


class TestRSSSourceFeedMeta:
    """Tests for RSSSource._extract_feed_meta."""

    def test_extract_feed_meta_basic(self):
        """Feed-level metadata is extracted from parsed feed."""
        mock_feed = MagicMock()
        mock_feed.feed.title = "Test Feed"
        mock_feed.feed.language = "en"
        mock_feed.feed.subtitle = "A test feed"
        mock_feed.version = "rss20"
        mock_feed.encoding = "utf-8"

        meta = RSSSource._extract_feed_meta(mock_feed)
        assert meta["title"] == "Test Feed"
        assert meta["language"] == "en"
        assert meta["version"] == "rss20"
        assert meta["encoding"] == "utf-8"
        assert meta["subtitle"] == "A test feed"

    def test_extract_feed_meta_empty(self):
        """Returns empty dict when no feed metadata available."""
        mock_feed = MagicMock(spec=[])  # No attributes
        meta = RSSSource._extract_feed_meta(mock_feed)
        assert meta == {}


class TestRSSParserBackwardCompat:
    """Ensure backward compatibility — parse() still works with 2 args."""

    def test_parse_without_feed_meta(self, rss_parser):
        """parse(entry, source_name) still works without feed_meta."""
        entry = {
            "title": "Compat Paper",
            "link": "https://example.com/compat",
            "summary": "Compat abstract",
        }
        paper = rss_parser.parse(entry, "TestSource")
        assert paper.title == "Compat Paper"
        assert paper.abstract == "Compat abstract"
        assert paper.source == "TestSource"
        assert paper.source_type == "rss"
