"""Unit tests for shared dedup helpers."""

from datetime import date

from src.models.responses import PaperItem
from src.utils.dedup import (
    deduplicate_papers,
    normalize_doi,
    normalize_title,
    normalize_url,
    paper_export_identity_keys,
    paper_export_identity_key,
    zotero_data_identity_keys,
)


def _paper(
    title: str,
    doi: str | None = None,
    url: str | None = None,
    published_date: date | None = None,
    authors: list[str] | None = None,
) -> PaperItem:
    return PaperItem(
        title=title,
        doi=doi,
        url=url,
        published_date=published_date,
        authors=authors or [],
        source="Test",
        source_type="rss",
    )


def test_normalizers_basic():
    assert normalize_doi("https://doi.org/10.1038/NATURE.12345") == "10.1038/nature.12345"
    assert normalize_title("An ASAP Study: In Press!") == "an study"
    assert (
        normalize_url(
            "HTTPS://Nature.com/article?utm_source=a&x=1&utm_medium=b&fbclid=abc"
        )
        == "https://nature.com/article?x=1"
    )


def test_deduplicate_papers_by_doi_url_and_title():
    p1 = _paper(
        title="Original Title",
        doi="10.1000/abc",
        url="https://doi.org/10.1000/abc",
    )
    p2 = _paper(
        title="Different Visible Title",
        doi="https://doi.org/10.1000/ABC",
        url="https://doi.org/10.1000/abc?utm_source=x",
    )
    p3 = _paper(
        title="A Paper In Press",
        url="https://example.org/paper",
    )
    p4 = _paper(
        title="A Paper",
        url="https://example.org/paper?utm_source=newsletter",
    )

    unique, stats = deduplicate_papers([p1, p2, p3, p4])

    assert len(unique) == 2
    assert stats["input_count"] == 4
    assert stats["dropped_count"] == 2
    assert stats["duplicates_by_key"]["doi"] == 1
    assert stats["duplicates_by_key"]["url"] == 1


def test_paper_export_identity_key_prefers_doi_then_title_date_then_url():
    with_doi = _paper(
        title="Same Paper",
        doi="10.2000/xyz",
        published_date=date(2025, 1, 1),
        url="https://example.org/with-doi",
    )
    no_doi = _paper(
        title="Same Paper",
        published_date=date(2025, 1, 1),
        url="https://example.org/no-doi",
    )
    no_doi_no_date = _paper(
        title="URL Only Paper",
        url="https://example.org/url-only?utm_source=a",
    )

    assert paper_export_identity_key(with_doi) == ("doi", "10.2000/xyz")
    assert paper_export_identity_key(no_doi) == (
        "title_date",
        "same paper|2025-01-01",
    )
    assert paper_export_identity_key(no_doi_no_date) == (
        "url",
        "https://example.org/url-only",
    )

    assert paper_export_identity_keys(no_doi) == [
        ("title_date", "same paper|2025-01-01"),
        ("url", "https://example.org/no-doi"),
    ]


def test_zotero_data_identity_keys_from_wrapped_payload():
    item = {
        "key": "ABC123",
        "data": {
            "title": "Sample Paper",
            "DOI": "doi:10.3000/kkk",
            "date": "2024-05-01",
            "url": "https://example.org/sample?utm_source=alert",
            "creators": [{"creatorType": "author", "name": "Jane Doe"}],
        },
    }

    keys = set(zotero_data_identity_keys(item))
    assert ("doi", "10.3000/kkk") in keys
    assert ("title_date", "sample paper|2024-05-01") in keys
    assert ("url", "https://example.org/sample") in keys
