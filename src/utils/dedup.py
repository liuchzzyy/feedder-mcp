"""Shared deduplication helpers for papers and Zotero items."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.models.responses import PaperItem
from src.utils.text import DOI_PATTERN

_TITLE_NOISE = re.compile(
    r"\b(ASAP|Just Accepted|Early Access|Ahead of Print|In Press)\b",
    re.IGNORECASE,
)
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "ref",
    "source",
}


def normalize_doi(value: Optional[str]) -> Optional[str]:
    """Normalize DOI-like text to lowercase bare DOI."""
    if not value:
        return None

    raw = value.strip()
    if not raw:
        return None

    lowered = raw.lower()
    if "doi.org/" in lowered:
        idx = lowered.rfind("doi.org/")
        raw = raw[idx + len("doi.org/") :]
    elif lowered.startswith("doi:"):
        raw = raw[4:]

    match = DOI_PATTERN.search(raw)
    if not match:
        return None

    doi = match.group(0).strip().rstrip(").,;")
    return doi.lower() if doi else None


def normalize_title(title: Optional[str]) -> str:
    """Normalize title text for stable dedup matching."""
    if not title:
        return ""
    t = title.lower().strip()
    t = _TITLE_NOISE.sub("", t)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_url(url: Optional[str]) -> Optional[str]:
    """Normalize URL by removing common tracking params and casing noise."""
    if not url:
        return None

    raw = url.strip()
    if not raw:
        return None

    doi = normalize_doi(raw)
    if doi and "doi.org/" in raw.lower():
        return f"https://doi.org/{doi}"

    parsed = urlparse(raw)
    if not parsed.netloc:
        return raw.rstrip("/")

    query_pairs = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = k.lower()
        if key_lower.startswith("utm_") or key_lower in _TRACKING_QUERY_KEYS:
            continue
        query_pairs.append((k, v))

    query_pairs.sort(key=lambda kv: (kv[0].lower(), kv[1]))
    clean_query = urlencode(query_pairs, doseq=True)
    clean_path = parsed.path.rstrip("/")

    return urlunparse(
        (
            (parsed.scheme or "https").lower(),
            parsed.netloc.lower(),
            clean_path,
            "",
            clean_query,
            "",
        )
    )


def identity_keys_for_paper(paper: PaperItem) -> List[Tuple[str, str]]:
    """Build all stable identity keys for a paper."""
    keys: List[Tuple[str, str]] = []

    doi = normalize_doi(paper.doi)
    if doi:
        keys.append(("doi", doi))

    url = normalize_url(paper.url)
    if url:
        keys.append(("url", url))

    title = normalize_title(paper.title)
    if title:
        keys.append(("title", title))

    return keys


def deduplicate_papers(
    papers: Iterable[PaperItem],
) -> Tuple[List[PaperItem], Dict[str, Any]]:
    """Deduplicate papers by DOI, URL, and normalized title."""
    unique: List[PaperItem] = []
    seen: Dict[Tuple[str, str], int] = {}
    duplicates_by_key: Dict[str, int] = {"doi": 0, "url": 0, "title": 0}
    kept_without_key = 0

    input_count = 0
    for paper in papers:
        input_count += 1
        keys = identity_keys_for_paper(paper)

        if not keys:
            kept_without_key += 1
            unique.append(paper)
            continue

        matched_kind: Optional[str] = None
        for key in keys:
            if key in seen:
                matched_kind = key[0]
                break

        if matched_kind:
            duplicates_by_key[matched_kind] = duplicates_by_key.get(matched_kind, 0) + 1
            continue

        new_index = len(unique)
        unique.append(paper)
        for key in keys:
            seen[key] = new_index

    dropped = input_count - len(unique)
    stats: Dict[str, Any] = {
        "input_count": input_count,
        "unique_count": len(unique),
        "dropped_count": dropped,
        "duplicates_by_key": duplicates_by_key,
        "kept_without_key": kept_without_key,
    }
    return unique, stats


def _normalize_date_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    if not text:
        return None

    normalized = re.sub(r"[./]", "-", text)

    ymd_match = re.search(r"\b((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})\b", normalized)
    if ymd_match:
        year, month, day = ymd_match.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"

    ym_match = re.search(r"\b((?:19|20)\d{2})-(\d{1,2})\b", normalized)
    if ym_match:
        year, month = ym_match.groups()
        return f"{year}-{int(month):02d}"

    year_match = re.search(r"\b((?:19|20)\d{2})\b", normalized)
    if year_match:
        return year_match.group(1)

    return None


def title_date_key(title: Optional[str], when: Any) -> Optional[str]:
    normalized_title = normalize_title(title)
    normalized_date = _normalize_date_text(when)
    if not normalized_title or not normalized_date:
        return None
    return f"{normalized_title}|{normalized_date}"


def paper_export_identity_keys(paper: PaperItem) -> List[Tuple[str, str]]:
    """Priority keys for Zotero export dedup: DOI -> title+date -> URL."""
    doi = normalize_doi(paper.doi)
    if doi:
        return [("doi", doi)]

    keys: List[Tuple[str, str]] = []
    title_date = title_date_key(paper.title, paper.published_date)
    if title_date:
        keys.append(("title_date", title_date))

    url = normalize_url(paper.url)
    if url:
        keys.append(("url", url))

    return keys


def paper_export_identity_key(paper: PaperItem) -> Optional[Tuple[str, str]]:
    """Backward-compatible single-key helper for Zotero export dedup."""
    keys = paper_export_identity_keys(paper)
    return keys[0] if keys else None


def zotero_data_identity_keys(raw_item: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Extract identity keys from a Zotero API item payload."""
    data = raw_item.get("data") if isinstance(raw_item.get("data"), dict) else raw_item
    if not isinstance(data, dict):
        return []

    keys: List[Tuple[str, str]] = []

    doi = normalize_doi(data.get("DOI"))
    if doi:
        keys.append(("doi", doi))

    title_date = title_date_key(data.get("title"), data.get("date"))
    if title_date:
        keys.append(("title_date", title_date))

    url = normalize_url(data.get("url"))
    if url:
        keys.append(("url", url))

    return keys
