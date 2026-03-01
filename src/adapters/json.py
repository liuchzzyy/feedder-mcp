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
        filepath: str = "exported_papers.json",
        include_metadata: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            output_path = Path(filepath)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with output_path.open("w", encoding="utf-8") as f:
                f.write("[\n")
                for idx, paper in enumerate(papers):
                    paper_dict = paper.model_dump(mode="json")
                    if not include_metadata:
                        paper_dict.pop("extra", None)
                    if idx > 0:
                        f.write(",\n")
                    f.write("  ")
                    json.dump(paper_dict, f, ensure_ascii=False)
                f.write("\n]\n")

            return {
                "count": len(papers),
                "filepath": str(output_path.absolute()),
                "success": True,
            }

        except (IOError, OSError) as e:
            raise IOError(f"Failed to write JSON file: {e}") from e

