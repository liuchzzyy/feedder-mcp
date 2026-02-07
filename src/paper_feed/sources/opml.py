"""OPML file parser for RSS feed sources."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


class OPMLParser:
    """Parser for OPML (Outline Processor Markup Language) files.

    OPML files contain lists of RSS feeds organized in categories/groups.
    This parser extracts RSS feed information including URLs, titles, and HTML URLs.

    Example OPML structure:
        <opml version="1.0">
          <body>
            <outline text="Category" title="Category">
              <outline type="rss" xmlUrl="..." title="..." htmlUrl="..." />
            </outline>
          </body>
        </opml>
    """

    def __init__(self, file_path: str):
        """Initialize OPML parser.

        Args:
            file_path: Path to OPML file
        """
        self.file_path = Path(file_path)

    def parse(self) -> List[Dict[str, str]]:
        """Parse OPML file and extract RSS feeds.

        Returns:
            List of RSS feed dictionaries with keys:
            - url: RSS feed URL (xmlUrl)
            - title: Feed title
            - html_url: Feed website URL (optional)
            - category: Parent category/group (optional)

        Raises:
            FileNotFoundError: If OPML file doesn't exist
            ET.ParseError: If OPML file is malformed
        """
        if not self.file_path.exists():
            raise FileNotFoundError(f"OPML file not found: {self.file_path}")

        feeds = []

        try:
            tree = ET.parse(self.file_path)
            root = tree.getroot()

            # Find body element
            body = root.find("body")
            if body is None:
                logger.warning(f"No body element found in {self.file_path}")
                return feeds

            # Process outline elements (handling nested categories)
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
        """Extract RSS feeds from an outline element.

        Args:
            outline: XML outline element
            category: Parent category name (if nested)

        Returns:
            List of RSS feed dictionaries
        """
        feeds = []

        # Check if this is an RSS feed (has xmlUrl attribute)
        xml_url = outline.get("xmlUrl")
        outline_type = outline.get("type")

        if xml_url and outline_type == "rss":
            # This is an RSS feed
            feed = {
                "url": xml_url,
                "title": outline.get("title", outline.get("text", "Unknown")),
                "html_url": outline.get("htmlUrl", ""),
            }

            # Add category if available
            if category:
                feed["category"] = category

            feeds.append(feed)
        else:
            # This might be a category/group - extract title and process children
            current_category = outline.get("title", outline.get("text", category))

            # Process nested outlines
            for child in outline.findall("outline"):
                feeds.extend(self._extract_feeds_from_outline(child, current_category))

        return feeds

    @classmethod
    def from_env(cls, env_var: str = "PAPER_FEED_OPML") -> "OPMLParser":
        """Create OPML parser from environment variable.

        Args:
            env_var: Environment variable name containing OPML file path

        Returns:
            OPMLParser instance

        Raises:
            ValueError: If environment variable not set
        """
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
        """Create OPML parser from default location.

        Args:
            default_path: Default OPML file path (relative to current directory)

        Returns:
            OPMLParser instance
        """
        # Check environment variable first
        env_path = os.environ.get("PAPER_FEED_OPML")
        if env_path:
            return cls(env_path)

        # Use default path
        return cls(default_path)


def parse_opml(file_path: str) -> List[Dict[str, str]]:
    """Convenience function to parse OPML file.

    Args:
        file_path: Path to OPML file

    Returns:
        List of RSS feed dictionaries

    Example:
        >>> feeds = parse_opml("feeds/RSS_official.opml")
        >>> for feed in feeds:
        ...     print(f"{feed['title']}: {feed['url']}")
    """
    parser = OPMLParser(file_path)
    return parser.parse()
