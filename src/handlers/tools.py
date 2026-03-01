"""MCP tool handler for feedder-mcp."""

import json
from typing import Any, Dict, List, Optional

from src.models.enums import ToolName
from src.models.responses import PaperItem
from src.models.schemas import (
    EnrichInput,
    ExportJSONInput,
    FetchGmailInput,
    FetchRSSInput,
    FilterAIInput,
    FilterKeywordsInput,
    GenerateKeywordsInput,
    SearchCrossrefInput,
    SearchOpenalexInput,
)
from src.services.enrich import EnrichService
from src.services.export import ExportService
from src.services.fetch import FetchService
from src.services.filter import FilterService
from src.utils.errors import format_error


def _papers_payload(papers: List[PaperItem]) -> Dict[str, Any]:
    return {
        "papers": [p.model_dump() for p in papers],
        "count": len(papers),
    }


def _ok(data: Any, meta: Optional[Dict[str, Any]] = None) -> str:
    payload: Dict[str, Any] = {"ok": True, "data": data}
    if meta:
        payload["meta"] = meta
    return json.dumps(payload, default=str, indent=2, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps(
        {"ok": False, "error": message},
        indent=2,
        ensure_ascii=False,
    )


def _parse_papers_json(papers_json: str) -> List[PaperItem]:
    data = json.loads(papers_json)
    if not isinstance(data, list):
        raise ValueError("papers_json must be a JSON array of paper objects")
    return [PaperItem(**item) for item in data]


class ToolHandler:
    """Handles listing and dispatching MCP tools."""

    def __init__(self) -> None:
        self.fetch_service = FetchService()
        self.filter_service = FilterService()
        self.enrich_service = EnrichService()
        self.export_service = ExportService()

    def get_tools(self) -> List[Any]:
        tools: List[Dict[str, Any]] = [
            {
                "name": ToolName.FETCH_RSS.value,
                "description": "Fetch papers from RSS feeds",
                "inputSchema": FetchRSSInput.model_json_schema(),
            },
            {
                "name": ToolName.FETCH_GMAIL.value,
                "description": "Fetch papers from Gmail alerts",
                "inputSchema": FetchGmailInput.model_json_schema(),
            },
            {
                "name": ToolName.FILTER_KEYWORDS.value,
                "description": "Filter papers by keyword criteria",
                "inputSchema": FilterKeywordsInput.model_json_schema(),
            },
            {
                "name": ToolName.FILTER_AI.value,
                "description": "AI-powered relevance filtering",
                "inputSchema": FilterAIInput.model_json_schema(),
            },
            {
                "name": ToolName.ENRICH.value,
                "description": "Enrich papers with CrossRef/OpenAlex",
                "inputSchema": EnrichInput.model_json_schema(),
            },
            {
                "name": ToolName.EXPORT_JSON.value,
                "description": "Export papers to JSON file",
                "inputSchema": ExportJSONInput.model_json_schema(),
            },
            {
                "name": ToolName.GENERATE_KEYWORDS.value,
                "description": "Generate research keywords",
                "inputSchema": GenerateKeywordsInput.model_json_schema(),
            },
            {
                "name": ToolName.SEARCH_CROSSREF.value,
                "description": "Search CrossRef by title",
                "inputSchema": SearchCrossrefInput.model_json_schema(),
            },
            {
                "name": ToolName.SEARCH_OPENALEX.value,
                "description": "Search OpenAlex by title",
                "inputSchema": SearchOpenalexInput.model_json_schema(),
            },
        ]

        try:
            from mcp.types import Tool  # type: ignore[import-untyped]

            return [Tool(**tool) for tool in tools]
        except Exception:
            return tools

    async def handle_tool(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, bool]:
        args = arguments or {}

        try:
            if name == ToolName.FETCH_RSS.value:
                payload = FetchRSSInput.model_validate(args)
                papers = await self.fetch_service.fetch_rss(
                    opml_path=payload.opml_path,
                    limit=payload.limit,
                    since=payload.since,
                )
                return _ok(_papers_payload(papers)), False

            if name == ToolName.FETCH_GMAIL.value:
                payload = FetchGmailInput.model_validate(args)
                papers = await self.fetch_service.fetch_gmail(
                    query=payload.query,
                    limit=payload.limit,
                    since=payload.since,
                )
                return _ok(_papers_payload(papers)), False

            if name == ToolName.FILTER_KEYWORDS.value:
                payload = FilterKeywordsInput.model_validate(args)
                result = await self.filter_service.filter_keywords(
                    papers_json=payload.papers_json,
                    keywords=payload.keywords,
                    exclude=payload.exclude,
                    authors=payload.authors,
                    min_date=payload.min_date,
                    has_pdf=payload.has_pdf,
                )
                return _ok(
                    {
                        "papers": [p.model_dump() for p in result.papers],
                        "total_count": result.total_count,
                        "passed_count": result.passed_count,
                        "rejected_count": result.rejected_count,
                        "filter_stats": result.filter_stats,
                    }
                ), False

            if name == ToolName.FILTER_AI.value:
                payload = FilterAIInput.model_validate(args)
                result = await self.filter_service.filter_ai(
                    papers_json=payload.papers_json,
                    research_prompt=payload.research_prompt,
                )
                return _ok(
                    {
                        "papers": [p.model_dump() for p in result.papers],
                        "total_count": result.total_count,
                        "passed_count": result.passed_count,
                        "rejected_count": result.rejected_count,
                        "filter_stats": result.filter_stats,
                    }
                ), False

            if name == ToolName.ENRICH.value:
                payload = EnrichInput.model_validate(args)
                papers = _parse_papers_json(payload.papers_json)
                enriched = await self.enrich_service.enrich(
                    papers,
                    provider=payload.provider,
                    concurrency=payload.concurrency,
                )
                return _ok(_papers_payload(enriched)), False

            if name == ToolName.EXPORT_JSON.value:
                payload = ExportJSONInput.model_validate(args)
                papers = _parse_papers_json(payload.papers_json)
                await self.export_service.export_json(
                    papers,
                    payload.filepath,
                    include_metadata=payload.include_metadata,
                )
                return _ok(
                    {
                        "exported_count": len(papers),
                        "filepath": payload.filepath,
                    }
                ), False

            if name == ToolName.GENERATE_KEYWORDS.value:
                payload = GenerateKeywordsInput.model_validate(args)
                keywords = await self.filter_service.generate_keywords(
                    research_prompt=payload.research_prompt
                )
                return _ok({"keywords": keywords}), False

            if name == ToolName.SEARCH_CROSSREF.value:
                payload = SearchCrossrefInput.model_validate(args)
                works = await self.enrich_service.search_crossref(payload.title)
                return _ok(
                    {
                        "results": [
                            self.enrich_service.crossref_work_to_dict(w)
                            for w in works
                        ],
                        "count": len(works),
                    }
                ), False

            if name == ToolName.SEARCH_OPENALEX.value:
                payload = SearchOpenalexInput.model_validate(args)
                works = await self.enrich_service.search_openalex(payload.title)
                return _ok(
                    {
                        "results": [
                            self.enrich_service.openalex_work_to_dict(w)
                            for w in works
                        ],
                        "count": len(works),
                    }
                ), False

            raise ValueError(f"Unknown tool: {name}")

        except Exception as exc:
            return _err(format_error(exc)), True

