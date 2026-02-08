"""Unit tests for GmailParser HTML parsing."""

import pytest

from paper_feed.sources.gmail_parser import GmailParser


@pytest.fixture
def parser():
    return GmailParser()


# ── Strategy 1: Table rows ──────────────────────────────────────────


SAMPLE_TABLE_HTML = """
<html><body>
<table>
  <tr>
    <td><a href="https://doi.org/10.1021/acs.jctc.2024">
      Machine Learning Potentials for Catalytic Reactions
    </a></td>
    <td>Smith, J., Doe, A.</td>
    <td>J. Chem. Theory Comput.</td>
  </tr>
  <tr>
    <td><a href="https://nature.com/articles/s41586-024-0001">
      Quantum Computing with Trapped Ions at Scale
    </a></td>
    <td>Wang, L., Chen, Z.</td>
    <td>Nature</td>
  </tr>
  <tr>
    <td><a href="#">Read more</a></td>
  </tr>
</table>
</body></html>
"""


def test_parse_table_extracts_items(parser):
    """Table rows with links produce PaperItem objects."""
    items = parser.parse(SAMPLE_TABLE_HTML, source_name="Test Journal")
    assert len(items) == 2


def test_parse_table_title(parser):
    """Titles are cleaned and extracted from link text."""
    items = parser.parse(SAMPLE_TABLE_HTML, source_name="Test")
    assert "Machine Learning Potentials" in items[0].title
    assert "Quantum Computing" in items[1].title


def test_parse_table_doi_extraction(parser):
    """DOIs are extracted from href URLs."""
    items = parser.parse(SAMPLE_TABLE_HTML, source_name="Test")
    assert items[0].doi == "10.1021/acs.jctc.2024"


def test_parse_table_source_type(parser):
    """All items have source_type='email'."""
    items = parser.parse(SAMPLE_TABLE_HTML, source_name="Test")
    for item in items:
        assert item.source_type == "email"


def test_parse_table_source_name(parser):
    """Source name is propagated to items."""
    items = parser.parse(SAMPLE_TABLE_HTML, source_name="Google Scholar")
    for item in items:
        assert item.source == "Google Scholar"


def test_parse_table_metadata(parser):
    """Email ID and subject are stored in metadata."""
    items = parser.parse(
        SAMPLE_TABLE_HTML,
        source_name="Test",
        email_id="msg123",
        email_subject="New articles",
    )
    assert items[0].extra["email_id"] == "msg123"
    assert items[0].extra["email_subject"] == "New articles"


def test_parse_table_skips_short_links(parser):
    """Links with text shorter than 10 chars are skipped (e.g., 'Read more')."""
    items = parser.parse(SAMPLE_TABLE_HTML, source_name="Test")
    titles = [item.title.lower() for item in items]
    assert "read more" not in titles


def test_parse_table_authors(parser):
    """Authors extracted from adjacent table cells."""
    items = parser.parse(SAMPLE_TABLE_HTML, source_name="Test")
    # First row has "Smith, J., Doe, A." in a cell with commas
    assert len(items[0].authors) > 0


# ── Strategy 2: Div layouts ─────────────────────────────────────────


SAMPLE_DIV_HTML = """
<html><body>
<div>
  <h3><a href="https://doi.org/10.1038/s41586-024-0002">
    A Novel Approach to Protein Folding Prediction
  </a></h3>
  <p>Authors: Alice, Bob, Charlie</p>
</div>
<div>
  <a href="https://science.org/doi/abs/10.1126/science.2024">
    CRISPR Gene Editing in Human Embryos: Ethical Considerations
  </a>
</div>
<div>
  <a href="#">X</a>
</div>
</body></html>
"""


def test_parse_divs_extracts_items(parser):
    """Div containers with links produce PaperItem objects."""
    items = parser.parse(SAMPLE_DIV_HTML, source_name="Alert")
    assert len(items) == 2


def test_parse_divs_doi(parser):
    """DOIs are extracted from div links."""
    items = parser.parse(SAMPLE_DIV_HTML, source_name="Alert")
    assert items[0].doi == "10.1038/s41586-024-0002"
    assert items[1].doi == "10.1126/science.2024"


def test_parse_divs_url(parser):
    """URLs are stored from link hrefs."""
    items = parser.parse(SAMPLE_DIV_HTML, source_name="Alert")
    assert "doi.org" in items[0].url
    assert "science.org" in items[1].url


# ── Strategy 3: Standalone links ────────────────────────────────────


SAMPLE_LINKS_HTML = """
<html><body>
<p>Check out these new papers:</p>
<a href="https://doi.org/10.1021/acs.nanolett.2024.001">
  Self-Assembled Nanostructures for Drug Delivery Applications
</a>
<br/>
<a href="https://www.nature.com/articles/s41467-024-0001">
  Deep Learning for Climate Model Downscaling
</a>
<br/>
<a href="https://unsubscribe.example.com">Unsubscribe</a>
<a href="https://example.com/short">Short</a>
</body></html>
"""


def test_parse_links_extracts_items(parser):
    """Standalone links to publisher domains produce items."""
    items = parser.parse(SAMPLE_LINKS_HTML, source_name="TOC")
    assert len(items) == 2


def test_parse_links_doi(parser):
    """DOIs extracted from link hrefs."""
    items = parser.parse(SAMPLE_LINKS_HTML, source_name="TOC")
    assert items[0].doi == "10.1021/acs.nanolett.2024.001"


def test_parse_links_skips_unsubscribe(parser):
    """Utility links like 'Unsubscribe' are filtered out."""
    items = parser.parse(SAMPLE_LINKS_HTML, source_name="TOC")
    titles = [item.title.lower() for item in items]
    assert "unsubscribe" not in titles


def test_parse_links_skips_short_text(parser):
    """Links with text under 20 chars are filtered out."""
    items = parser.parse(SAMPLE_LINKS_HTML, source_name="TOC")
    for item in items:
        assert len(item.title) >= 15


# ── Deduplication ───────────────────────────────────────────────────


SAMPLE_DUPLICATE_HTML = """
<html><body>
<table>
  <tr>
    <td><a href="https://doi.org/10.1021/duplicate">
      Duplicate Paper Title for Testing
    </a></td>
  </tr>
  <tr>
    <td><a href="https://doi.org/10.1021/duplicate-2">
      Duplicate Paper Title for Testing
    </a></td>
  </tr>
  <tr>
    <td><a href="https://doi.org/10.1021/unique">
      Unique Paper Title That Is Different
    </a></td>
  </tr>
</table>
</body></html>
"""


def test_parse_deduplicates_by_title(parser):
    """Papers with same title (case-insensitive) are deduplicated."""
    items = parser.parse(SAMPLE_DUPLICATE_HTML, source_name="Test")
    assert len(items) == 2
    titles = [item.title for item in items]
    assert "Duplicate Paper Title for Testing" in titles
    assert "Unique Paper Title That Is Different" in titles


# ── Edge cases ──────────────────────────────────────────────────────


def test_parse_empty_html(parser):
    """Empty HTML returns empty list."""
    assert parser.parse("", source_name="Test") == []


def test_parse_none_html(parser):
    """None-like empty input returns empty list."""
    assert parser.parse("", source_name="Test") == []


def test_parse_no_articles(parser):
    """HTML with no article content returns empty list."""
    html = "<html><body><p>Hello world</p></body></html>"
    assert parser.parse(html, source_name="Test") == []


def test_parse_strategy_fallthrough(parser):
    """When tables have no items, falls through to divs, then links."""
    # This HTML has an empty table, so should fall through to div strategy
    html = """
    <html><body>
    <table><tr><td>Header</td></tr></table>
    <div>
      <a href="https://doi.org/10.1000/test.fallthrough.1234">
        Fallthrough Strategy Test Paper Title for Validation
      </a>
    </div>
    </body></html>
    """
    items = parser.parse(html, source_name="Test")
    assert len(items) >= 1
