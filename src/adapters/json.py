"""JSON export adapter for feedder-mcp."""

import json
from pathlib import Path
from typing import List, Dict, Any

from src.models.responses import ExportAdapter, PaperItem


class JSONAdapter(ExportAdapter):
    """Export papers to JSON file."""

    adapter_name: str = "json"

    async def export(
        self,
        papers: List[PaperItem],
        filepath: str = "papers.json",
        include_metadata: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            papers_data = []
            for paper in papers:
                paper_dict = paper.model_dump(mode="json")

                if not include_metadata:
                    paper_dict.pop("extra", None)

                papers_data.append(paper_dict)

            output_path = Path(filepath)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with output_path.open("w", encoding="utf-8") as f:
                json.dump(papers_data, f, indent=2, ensure_ascii=False)

            return {
                "count": len(papers_data),
                "filepath": str(output_path.absolute()),
                "success": True,
            }

        except (IOError, OSError) as e:
            raise IOError(f"Failed to write JSON file: {e}") from e

