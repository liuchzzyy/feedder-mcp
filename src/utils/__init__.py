"""Utility functions for feedder-mcp."""

from src.utils.dedup import (
    deduplicate_papers,
    identity_keys_for_paper,
    normalize_doi,
    normalize_title,
    normalize_url,
    paper_export_identity_keys,
    paper_export_identity_key,
    zotero_data_identity_keys,
)
from src.utils.text import DOI_PATTERN, clean_abstract, clean_html, clean_title

__all__ = [
    "DOI_PATTERN",
    "clean_title",
    "clean_html",
    "clean_abstract",
    "normalize_doi",
    "normalize_title",
    "normalize_url",
    "identity_keys_for_paper",
    "deduplicate_papers",
    "paper_export_identity_keys",
    "paper_export_identity_key",
    "zotero_data_identity_keys",
]

