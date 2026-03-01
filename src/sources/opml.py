"""OPML file parser for RSS feed sources."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class OPMLParser:
    """Parser for OPML (Outline Processor Markup Language) files."""

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)

    def parse(self) -> List[Dict[str, str]]:
        """Parse OPML file and extract RSS feeds."""
        if not self.file_path.exists():
            raise FileNotFoundError(f"OPML file not found: {self.file_path}")

        feeds = []

        try:
            tree = ET.parse(self.file_path)
            root = tree.getroot()

            body = root.find("body")
            if body is None:
                logger.warning(f"No body element found in {self.file_path}")
                return feeds

            for outline in body.findall("outline"):
                feeds.extend(self._extract_feeds_from_outline(outline))

            logger.info(f"Parsed {len(feeds)} RSS feeds from {self.file_path}")
            return feeds

        except ET.ParseError as e:
            logger.error(f"Failed to parse OPML file {self.file_path}: {e}")
            raise

    def _extract_feeds_from_outline(
        self, outline: ET.Element, category: Optional[str] = None
    ) -> List[Dict[str, str]]:
        feeds = []

        xml_url = outline.get("xmlUrl")
        outline_type = (outline.get("type") or "").strip().lower()

        if xml_url and (not outline_type or outline_type in {"rss", "atom"}):
            feed = {
                "url": xml_url,
                "title": outline.get("title", outline.get("text", "Unknown")),
                "html_url": outline.get("htmlUrl", ""),
            }
            if category:
                feed["category"] = category
            feeds.append(feed)

        current_category = outline.get("title", outline.get("text", category))
        for child in outline.findall("outline"):
            feeds.extend(self._extract_feeds_from_outline(child, current_category))

        return feeds

    @classmethod
    def from_env(cls, env_var: str = "PAPER_FEEDDER_MCP_OPML") -> "OPMLParser":
        opml_path = os.environ.get(env_var)
        if not opml_path:
            raise ValueError(
                f"Environment variable {env_var} not set. "
                f"Please set it to your OPML file path."
            )
        return cls(opml_path)

    @classmethod
    def from_default_location(
        cls, default_path: str = "feeds/RSS_official.opml"
    ) -> "OPMLParser":
        env_path = os.environ.get("PAPER_FEEDDER_MCP_OPML")
        if env_path:
            return cls(env_path)
        return cls(default_path)


def parse_opml(file_path: str) -> List[Dict[str, str]]:
    """Convenience function to parse OPML file."""
    parser = OPMLParser(file_path)
    return parser.parse()
