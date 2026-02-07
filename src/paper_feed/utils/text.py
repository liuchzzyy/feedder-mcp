"""Text cleaning utilities for paper-feed.

Provides functions for cleaning titles, HTML content, and abstracts
commonly found in RSS feeds and email alerts.
"""

import html
import re
from typing import Optional

# Precompiled regex for HTML tag removal
_HTML_TAG_PATTERN = re.compile(r"<.*?>")

# Shared DOI regex pattern used by RSS and Gmail sources
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def clean_title(title: str) -> str:
    """Clean article title by removing common prefixes.

    Removes prefixes like [DOI], [PDF], [HTML], etc. from article titles,
    and strips excess whitespace.

    Args:
        title: The raw title string.

    Returns:
        Cleaned title string.

    Examples:
        >>> clean_title("[DOI] 10.1234/example The paper title")
        '10.1234/example The paper title'
        >>> clean_title("[PDF] Research Article")
        'Research Article'
        >>> clean_title("  Normal Title  ")
        'Normal Title'
    """
    if not title:
        return ""
    cleaned = re.sub(r"^\[.*?\]\s*", "", title)
    return cleaned.strip()


def clean_html(raw_html: str) -> str:
    """Remove HTML tags from a string.

    Args:
        raw_html: String containing HTML content.

    Returns:
        Cleaned string without HTML tags.

    Examples:
        >>> clean_html("<p>Hello <b>world</b></p>")
        'Hello world'
        >>> clean_html("No HTML here")
        'No HTML here'
    """
    if not raw_html:
        return ""
    return re.sub(_HTML_TAG_PATTERN, "", raw_html)


def clean_abstract(abstract: Optional[str]) -> Optional[str]:
    """Clean abstract text by removing HTML/XML tags and entities.

    Removes:
    - HTML/XML tags (<...>)
    - HTML entities (&amp;, &lt;, etc.)
    - JATS XML tags (specific to academic publishing)
    - Extra whitespace and newlines
    - Embedded DOI/URL patterns

    Args:
        abstract: Raw abstract text that may contain HTML/XML.

    Returns:
        Clean plain text abstract, or None if input is empty/None.

    Examples:
        >>> clean_abstract("<p>This is an abstract</p>")
        'This is an abstract'
        >>> clean_abstract("Text with &amp; entity")
        'Text with & entity'
        >>> clean_abstract(None)
    """
    if not abstract:
        return None

    # Decode HTML entities first (e.g., &amp; -> &, &lt; -> <)
    try:
        abstract = html.unescape(abstract)
    except Exception:
        pass

    # Remove XML/HTML tags (including self-closing tags)
    abstract = re.sub(r"<[^>]+>", "", abstract)

    # Remove common JATS/XML-specific patterns
    abstract = re.sub(r"</?(?:jats:[^>]+|xref|sup|sub|italic|bold|sc)>", "", abstract)

    # Remove DOI/URL patterns sometimes embedded in abstracts
    abstract = re.sub(r"https?://doi\.org/[^\s]+", "", abstract)
    abstract = re.sub(r"DOI:\s*[^\s]+", "", abstract)

    # Clean up whitespace:
    # - Replace multiple spaces/newlines with single space
    # - Remove leading/trailing whitespace
    abstract = re.sub(r"\s+", " ", abstract)
    abstract = abstract.strip()

    # Return None if empty after cleaning
    return abstract if abstract else None
