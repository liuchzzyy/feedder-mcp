"""Abstract base classes for paper-feed."""

from abc import ABC, abstractmethod
from typing import Any, List, Optional
from datetime import date

from paper_feed.core.models import PaperItem


class PaperSource(ABC):
    """Abstract base class for paper data sources.

    Subclasses implement specific source types (RSS, Gmail, etc.)
    """

    source_name: str = "base"
    source_type: str = "base"

    @abstractmethod
    async def fetch_papers(
        self, limit: Optional[int] = None, since: Optional[date] = None
    ) -> List[PaperItem]:
        """Fetch papers from this data source.

        Args:
            limit: Maximum number of papers to return
            since: Only return papers published after this date

        Returns:
            List of PaperItem objects
        """
        pass


class ExportAdapter(ABC):
    """Abstract base class for export adapters.

    Subclasses implement export to specific targets (Zotero, JSON, etc.)
    """

    @abstractmethod
    async def export(self, papers: List[PaperItem], **kwargs: Any) -> Any:
        """Export papers to target system.

        Args:
            papers: List of papers to export
            **kwargs: Adapter-specific parameters
        """
        pass
