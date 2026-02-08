"""Zotero export adapter for paper-feed.

This adapter requires zotero-core to be installed. It provides optional
export functionality to Zotero libraries via the Zotero API.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime

from paper_feed.core.base import ExportAdapter
from paper_feed.core.models import PaperItem

# Check for optional zotero-core dependency
try:
    from zotero_core import ItemService  # type: ignore[import-unresolved]

    zotero_available = True
except ImportError:
    zotero_available = False
    ItemService = None


class ZoteroAdapter(ExportAdapter):
    """Export papers to Zotero library.

    This adapter converts PaperItem objects to Zotero item format and imports
    them into a Zotero library via the Zotero API.

    Attributes:
        adapter_name: Name identifier for this adapter
        library_id: Zotero library ID (user or group)
        api_key: Zotero API key
        library_type: Type of library ("user" or "group")
    """

    adapter_name: str = "zotero"

    def __init__(
        self,
        library_id: str,
        api_key: str,
        library_type: str = "user",
    ):
        """Initialize Zotero adapter.

        Args:
            library_id: Zotero library ID (user ID or group ID)
            api_key: Zotero API key with write permissions
            library_type: Type of library ("user" or "group")

        Raises:
            ImportError: If zotero-core is not installed
        """
        if not zotero_available:
            raise ImportError(
                "zotero-core is required for ZoteroAdapter. "
                "Install it with: pip install zotero-core"
            )

        self.library_id = library_id
        self.api_key = api_key
        self.library_type = library_type

    async def export(
        self,
        papers: List[PaperItem],
        collection_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Export papers to Zotero library.

        Args:
            papers: List of papers to export
            collection_id: Optional Zotero collection ID to add items to

        Returns:
            Dict with export results:
                - success_count: Number of successfully imported papers
                - total: Total number of papers attempted
                - failures: List of failed paper titles
        """
        if not zotero_available:
            raise ImportError(
                "zotero-core is required for ZoteroAdapter. "
                "Install it with: pip install zotero-core"
            )

        # Initialize ItemService
        assert ItemService is not None
        service = ItemService(
            library_id=self.library_id,
            api_key=self.api_key,
            library_type=self.library_type,
        )

        success_count = 0
        failures = []

        for paper in papers:
            try:
                # Convert to Zotero item format
                zotero_item = self._paper_to_zotero_item(paper)

                # Create item in Zotero
                await service.create_item(zotero_item, collection_id=collection_id)
                success_count += 1

            except Exception as e:
                failures.append(
                    {
                        "title": paper.title,
                        "error": str(e),
                    }
                )

        return {
            "success_count": success_count,
            "total": len(papers),
            "failures": failures,
        }

    def _paper_to_zotero_item(self, paper: PaperItem) -> Dict[str, Any]:
        """Convert PaperItem to Zotero item format.

        Maps all PaperItem fields to Zotero journalArticle schema fields.

        Args:
            paper: PaperItem to convert

        Returns:
            Dict in Zotero item format (journalArticle)
        """
        # Convert authors to Zotero creator format
        creators = [
            {"creatorType": "author", "name": author} for author in paper.authors
        ]

        # Format dates (ISO format)
        date_str = None
        if paper.published_date:
            date_str = paper.published_date.isoformat()

        access_date_str = None
        if paper.access_date:
            access_date_str = paper.access_date.isoformat()
        else:
            access_date_str = datetime.now().strftime("%Y-%m-%d")

        # Build Zotero item with all mapped fields
        zotero_item: Dict[str, Any] = {
            "itemType": paper.item_type or "journalArticle",
            "title": paper.title,
            "creators": creators,
            "abstractNote": paper.abstract or None,
            "publicationTitle": paper.publication_title,
            "journalAbbreviation": paper.journal_abbreviation,
            "publisher": paper.publisher,
            "place": paper.place,
            "volume": paper.volume,
            "issue": paper.issue,
            "pages": paper.pages,
            "section": paper.section,
            "partNumber": paper.part_number,
            "partTitle": paper.part_title,
            "series": paper.series,
            "seriesTitle": paper.series_title,
            "seriesText": paper.series_text,
            "DOI": paper.doi,
            "citationKey": paper.citation_key,
            "url": paper.url,
            "accessDate": access_date_str,
            "PMID": paper.pmid,
            "PMCID": paper.pmcid,
            "ISSN": paper.issn,
            "archive": paper.archive,
            "archiveLocation": paper.archive_location,
            "shortTitle": paper.short_title,
            "language": paper.language,
            "libraryCatalog": paper.library_catalog,
            "callNumber": paper.call_number,
            "rights": paper.rights,
            "date": date_str,
            "tags": [],
        }

        # Remove None/empty values
        zotero_item = {k: v for k, v in zotero_item.items() if v is not None}

        return zotero_item
