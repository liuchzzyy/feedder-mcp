"""JSON export adapter for paper-feed."""

import json
from pathlib import Path
from typing import List, Dict, Any

from paper_feed.core.base import ExportAdapter
from paper_feed.core.models import PaperItem


class JSONAdapter(ExportAdapter):
    """Export papers to JSON file.

    This adapter converts PaperItem objects to JSON format and writes them to a file.
    Supports optional inclusion of raw metadata for debugging or archival purposes.

    Attributes:
        adapter_name: Name identifier for this adapter
    """

    adapter_name: str = "json"

    async def export(
        self,
        papers: List[PaperItem],
        filepath: str = "papers.json",
        include_metadata: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Export papers to JSON file.

        Args:
            papers: List of papers to export
            filepath: Path to output JSON file
            include_metadata: Whether to include raw metadata field

        Returns:
            Dict with export results:
                - count: Number of papers exported
                - filepath: Path to output file
                - success: True if export succeeded

        Raises:
            IOError: If file write fails
        """
        try:
            # Convert papers to list of dicts with JSON-serializable values
            papers_data = []
            for paper in papers:
                paper_dict = paper.model_dump()

                # Convert date objects to ISO format strings
                if paper_dict.get("published_date"):
                    paper_dict["published_date"] = paper_dict[
                        "published_date"
                    ].isoformat()

                # Optionally exclude raw metadata
                if not include_metadata:
                    paper_dict.pop("metadata", None)

                papers_data.append(paper_dict)

            # Ensure parent directory exists
            output_path = Path(filepath)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Write to file with proper formatting
            with output_path.open("w", encoding="utf-8") as f:
                json.dump(papers_data, f, indent=2, ensure_ascii=False)

            return {
                "count": len(papers_data),
                "filepath": str(output_path.absolute()),
                "success": True,
            }

        except (IOError, OSError) as e:
            raise IOError(f"Failed to write JSON file: {e}") from e
