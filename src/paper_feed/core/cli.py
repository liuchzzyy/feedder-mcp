"""Command-line interface for paper-feed.

Provides subcommands for fetching, filtering, exporting, and
enriching academic papers. Entry point is configured in
pyproject.toml as ``paper-feed = "paper_feed.core.cli:main"``.

命令行接口：从 RSS 订阅源和邮件提醒中收集、过滤和导出学术论文。
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import date
from pathlib import Path
from typing import List

from paper_feed.core.models import PaperItem

logger = logging.getLogger(__name__)


# -------------------- Helpers --------------------


def _load_papers(path: str) -> List[PaperItem]:
    """Load papers from a JSON file.

    Args:
        path: Path to JSON file containing paper list.

    Returns:
        List of PaperItem objects.

    Raises:
        SystemExit: If file cannot be read or parsed.
    """
    filepath = Path(path)
    if not filepath.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        raw = json.loads(filepath.read_text(encoding="utf-8"))
        return [PaperItem(**item) for item in raw]
    except Exception as e:
        print(
            f"Error loading papers from {path}: {e}",
            file=sys.stderr,
        )
        sys.exit(1)


def _save_papers(papers: List[PaperItem], path: str) -> None:
    """Save papers to a JSON file.

    Args:
        papers: List of PaperItem objects.
        path: Output file path.
    """
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    data = [p.model_dump() for p in papers]
    filepath.write_text(
        json.dumps(data, default=str, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# -------------------- Handlers --------------------


async def _handle_fetch(args: argparse.Namespace) -> None:
    """Handle the 'fetch' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    since = None
    if args.since:
        since = date.fromisoformat(args.since)

    if args.source == "rss":
        from paper_feed.sources.rss import RSSSource

        opml_path = args.opml
        if not opml_path:
            from paper_feed.core.config import get_rss_config

            opml_path = get_rss_config()["opml_path"]

        source = RSSSource(opml_path)
        papers = await source.fetch_papers(limit=args.limit, since=since)
    elif args.source == "gmail":
        from paper_feed.sources.gmail import GmailSource

        query = args.query or "is:unread"
        source = GmailSource(query=query)
        papers = await source.fetch_papers(limit=args.limit, since=since)
    else:
        print(
            f"Error: unknown source: {args.source}",
            file=sys.stderr,
        )
        sys.exit(1)

    _save_papers(papers, args.output)
    print(f"Fetched {len(papers)} papers → {args.output}")


async def _handle_filter(args: argparse.Namespace) -> None:
    """Handle the 'filter' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    from paper_feed.core.models import FilterCriteria
    from paper_feed.filters.pipeline import FilterPipeline

    papers = _load_papers(args.input)

    min_date = None
    if args.min_date:
        min_date = date.fromisoformat(args.min_date)

    criteria = FilterCriteria(
        keywords=args.keywords or [],
        exclude_keywords=args.exclude or [],
        authors=args.authors or [],
        min_date=min_date,
        has_pdf=args.has_pdf,
    )

    # Set up AI filtering if requested
    llm_client = None
    if args.ai:
        from openai import OpenAI

        from paper_feed.core.config import get_openai_config

        config = get_openai_config()
        api_key = config.get("api_key")
        if api_key:
            kwargs = {"api_key": api_key}
            base_url = config.get("base_url")
            if base_url:
                kwargs["base_url"] = base_url
            llm_client = OpenAI(**kwargs)
        else:
            print(
                "Warning: --ai requested but OPENAI_API_KEY "
                "not set. Skipping AI filter.",
                file=sys.stderr,
            )

    pipeline = FilterPipeline(llm_client=llm_client)
    result = await pipeline.filter(papers, criteria)

    _save_papers(result.papers, args.output)
    print(
        f"Filtered: {result.passed_count} passed, "
        f"{result.rejected_count} rejected "
        f"(from {result.total_count} total) → {args.output}"
    )


async def _handle_export(args: argparse.Namespace) -> None:
    """Handle the 'export' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    papers = _load_papers(args.input)

    if args.format == "json":
        from paper_feed.adapters.json import JSONAdapter

        adapter = JSONAdapter()
        await adapter.export(
            papers,
            args.output,
            include_metadata=args.include_metadata,
        )
    elif args.format == "zotero":
        from paper_feed.adapters.zotero import ZoteroAdapter
        from paper_feed.core.config import get_zotero_config

        zotero_config = get_zotero_config()
        adapter = ZoteroAdapter(
            library_id=zotero_config["library_id"],
            api_key=zotero_config["api_key"],
            library_type=zotero_config.get("library_type", "user"),
        )
        await adapter.export(papers)
    else:
        print(
            f"Error: unknown format: {args.format}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Exported {len(papers)} papers ({args.format}) → {args.output}")


async def _handle_enrich(args: argparse.Namespace) -> None:
    """Handle the 'enrich' subcommand.

    Args:
        args: Parsed CLI arguments.
    """
    papers = _load_papers(args.input)

    use_crossref = args.source in ("crossref", "all")
    use_openalex = args.source in ("openalex", "all")

    semaphore = asyncio.Semaphore(args.concurrency)

    async def _enrich_one(paper: PaperItem) -> PaperItem:
        async with semaphore:
            result = paper
            enriched = False

            if use_crossref:
                from paper_feed.sources.crossref import (
                    CrossrefClient,
                )

                client = CrossrefClient()
                try:
                    result = await client.enrich_paper(result)
                    # Check if enrichment actually added data
                    if result is not None and (
                        result.doi != paper.doi
                        or result.authors != paper.authors
                        or result.published_date != paper.published_date
                    ):
                        enriched = True
                    result = result
                finally:
                    await client.close()

            if use_openalex and not enriched:
                from paper_feed.sources.openalex import (
                    OpenAlexClient,
                )

                client = OpenAlexClient()
                try:
                    result = await client.enrich_paper(result)
                    # Check if enrichment actually added data
                    if result is not None and (
                        result.doi != paper.doi
                        or result.authors != paper.authors
                        or result.published_date != paper.published_date
                    ):
                        enriched = True
                    result = result
                finally:
                    await client.close()

            # Always return result (enriched or original)
            # 没有 DOI 的论文也会被保留
            return result

    tasks = [_enrich_one(p) for p in papers]
    results = await asyncio.gather(*tasks)

    # Remove None values (if any enrichment failed completely)
    final_papers = [p for p in results if p is not None]

    _save_papers(list(final_papers), args.output)

    enriched_count = sum(1 for orig, enr in zip(papers, final_papers) if orig != enr)
    print(f"Enriched {enriched_count}/{len(papers)} papers → {args.output}")


# -------------------- CLI Setup --------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="paper-feed",
        description=(
            "Collect, filter, and export academic papers "
            "from RSS feeds and email alerts.\n"
            "从 RSS 订阅源和邮件提醒中收集、过滤和导出学术论文。"
        ),
    )
    subparsers = parser.add_subparsers(
        dest="command", help="Available commands | 可用命令"
    )

    # ---- fetch ----
    fetch_parser = subparsers.add_parser(
        "fetch", help="Fetch papers from a source | 从数据源获取论文"
    )
    fetch_parser.add_argument(
        "-s",
        "--source",
        choices=["rss", "gmail"],
        default="rss",
        help="Data source (default: rss) | 数据源（默认：rss）",
    )
    fetch_parser.add_argument(
        "--opml",
        "--rss-feeds",
        dest="opml",
        help="OPML file path (for RSS source) | OPML 文件路径（RSS 源）",
    )
    fetch_parser.add_argument(
        "-q",
        "--query",
        "--gmail-query",
        dest="query",
        help="Gmail search query (for Gmail source) | Gmail 搜索查询（Gmail 源）",
    )
    fetch_parser.add_argument(
        "-n",
        "--limit",
        "--max-papers",
        dest="limit",
        type=int,
        help="Maximum number of papers to fetch | 最大论文获取数量",
    )
    fetch_parser.add_argument(
        "--since",
        "--from-date",
        dest="since",
        help="Only fetch papers since date (YYYY-MM-DD) | 仅获取此日期之后的论文（YYYY-MM-DD）",
    )
    fetch_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output JSON file path | 输出 JSON 文件路径",
    )

    # ---- filter ----
    filter_parser = subparsers.add_parser(
        "filter", help="Filter papers by criteria | 按条件过滤论文"
    )
    filter_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input JSON file with papers | 输入 JSON 文件（包含论文）",
    )
    filter_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output JSON file path | 输出 JSON 文件路径",
    )
    filter_parser.add_argument(
        "-k",
        "--keywords",
        nargs="+",
        help="Required keywords (OR logic, first-pass filter) | 关键词（OR 逻辑，一级过滤）",
    )
    filter_parser.add_argument(
        "-x",
        "--exclude",
        "--exclude-keywords",
        dest="exclude",
        nargs="+",
        help="Exclude keywords (NOT logic) | 排除关键词（NOT 逻辑）",
    )
    filter_parser.add_argument(
        "-a",
        "--authors",
        nargs="+",
        help="Author filter (OR logic) | 作者过滤（OR 逻辑）",
    )
    filter_parser.add_argument(
        "--min-date",
        "--after",
        "--from",
        dest="min_date",
        help="Minimum publication date (YYYY-MM-DD) | 最早发表日期（YYYY-MM-DD）",
    )
    filter_parser.add_argument(
        "--pdf",
        "--has-pdf",
        "--require-pdf",
        dest="has_pdf",
        action="store_true",
        help="Require PDF availability | 要求有 PDF",
    )
    filter_parser.add_argument(
        "--ai",
        "--semantic",
        "--use-ai",
        dest="ai",
        action="store_true",
        help="Enable AI-powered relevance filtering | 启用 AI 语义相关性过滤",
    )

    # ---- export ----
    export_parser = subparsers.add_parser(
        "export", help="Export papers to a format | 导出论文到指定格式"
    )
    export_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input JSON file with papers | 输入 JSON 文件（包含论文）",
    )
    export_parser.add_argument(
        "-f",
        "--format",
        choices=["json", "zotero"],
        default="json",
        help="Export format (default: json) | 导出格式（默认：json）",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output file path | 输出文件路径",
    )
    export_parser.add_argument(
        "-m",
        "--metadata",
        "--include-metadata",
        "--with-metadata",
        dest="include_metadata",
        action="store_true",
        help="Include metadata in export | 导出时包含元数据",
    )

    # ---- enrich ----
    enrich_parser = subparsers.add_parser(
        "enrich",
        help="Enrich papers with CrossRef/OpenAlex metadata | 使用 CrossRef/OpenAlex 补充论文元数据",
    )
    enrich_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Input JSON file with papers | 输入 JSON 文件（包含论文）",
    )
    enrich_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output JSON file path | 输出 JSON 文件路径",
    )
    enrich_parser.add_argument(
        "--api",
        "--source",
        "--provider",
        dest="source",
        choices=["crossref", "openalex", "all"],
        default="all",
        help="Enrichment API provider (default: all) | 元数据 API 提供商（默认：all）",
    )
    enrich_parser.add_argument(
        "-j",
        "--jobs",
        "--concurrency",
        "--parallel",
        dest="concurrency",
        type=int,
        default=5,
        help="Max concurrent API requests (default: 5) | 最大并发 API 请求数（默认：5）",
    )

    return parser


def main() -> None:
    """CLI entry point for paper-feed."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    handlers = {
        "fetch": _handle_fetch,
        "filter": _handle_filter,
        "export": _handle_export,
        "enrich": _handle_enrich,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    assert handler is not None
    try:
        asyncio.run(handler(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        logger.debug("Full traceback:", exc_info=True)
        sys.exit(1)
