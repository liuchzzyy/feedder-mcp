"""Command-line interface for feedder-mcp."""

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path
import shutil
from typing import List

from src.config.settings import (
    get_openai_config,
    get_rss_config,
    get_zotero_config,
)
from src.models.responses import FilterCriteria, FilterResult, PaperItem
from src.server import serve

logger = logging.getLogger(__name__)


# -------------------- Helpers --------------------


def _load_papers(path: str) -> List[PaperItem]:
    filepath = Path(path)
    if not filepath.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        raw = json.loads(filepath.read_text(encoding="utf-8"))
        return [PaperItem(**item) for item in raw]
    except Exception as exc:
        print(
            f"Error loading papers from {path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def _save_papers(papers: List[PaperItem], path: str) -> None:
    filepath = Path(path)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    data = [p.model_dump() for p in papers]
    filepath.write_text(
        json.dumps(data, default=str, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# -------------------- Handlers --------------------


async def _handle_fetch(args: argparse.Namespace) -> None:
    since = None
    if args.since:
        since = date.fromisoformat(args.since)

    if args.source == "rss":
        from src.sources.rss import RSSSource

        opml_path = args.opml
        if not opml_path:
            opml_path = get_rss_config()["opml_path"]

        source = RSSSource(opml_path)
        papers = await source.fetch_papers(limit=args.limit, since=since)
    elif args.source == "gmail":
        from src.sources.gmail import GmailSource

        query = args.query
        source = GmailSource(query=query)
        papers = await source.fetch_papers(limit=args.limit, since=since)
    else:
        print(
            f"Error: unknown source: {args.source}",
            file=sys.stderr,
        )
        sys.exit(1)

    _save_papers(papers, args.output)
    print(f"Fetched {len(papers)} papers -> {args.output}")


async def _handle_filter(args: argparse.Namespace) -> None:
    from src.filters.pipeline import FilterPipeline

    papers = _load_papers(args.input)

    min_date = None
    if args.min_date:
        min_date = date.fromisoformat(args.min_date)

    keywords = args.keywords or []
    if not keywords:
        from src.ai.keyword_generator import KeywordGenerator

        try:
            keywords = await KeywordGenerator().extract_keywords()
            if keywords:
                print(
                    f"Auto-generated keywords from RESEARCH_PROMPT: {keywords}"
                )
            else:
                print(
                    "Error: no keywords available. "
                    "Provide --keywords or configure RESEARCH_PROMPT with a valid AI API key.",
                    file=sys.stderr,
                )
                sys.exit(1)
        except Exception as exc:
            print(
                f"Error: failed to generate keywords from RESEARCH_PROMPT: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    criteria = FilterCriteria(
        keywords=keywords,
        exclude_keywords=args.exclude or [],
        authors=args.authors or [],
        min_date=min_date,
        has_pdf=args.has_pdf,
    )

    llm_client = None
    if args.ai:
        from openai import OpenAI

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
                "Warning: AI filtering enabled but OPENAI_API_KEY not set. "
                "Skipping AI filter.",
                file=sys.stderr,
            )

    pipeline = FilterPipeline(llm_client=llm_client)
    result: FilterResult = await pipeline.filter(papers, criteria)

    _save_papers(result.papers, args.output)
    print(
        f"Filtered: {result.passed_count} passed, "
        f"{result.rejected_count} rejected "
        f"(from {result.total_count} total) -> {args.output}"
    )


async def _handle_export(args: argparse.Namespace) -> None:
    papers = _load_papers(args.input)
    input_name = Path(args.input).name.lower()
    if input_name == "raw.json":
        print(
            "Warning: exporting from raw.json means filter step was not applied.",
            file=sys.stderr,
        )

    if args.format == "json":
        from src.adapters.json import JSONAdapter

        adapter = JSONAdapter()
        await adapter.export(
            papers,
            args.output,
            include_metadata=args.include_metadata,
        )
    elif args.format == "zotero":
        from src.adapters.zotero import ZoteroAdapter

        zotero_config = get_zotero_config()
        collection_id = (
            getattr(args, "collection", None)
            or zotero_config.get("target_collection")
        )
        adapter = ZoteroAdapter(
            library_id=zotero_config["library_id"],
            api_key=zotero_config["api_key"],
            library_type=zotero_config.get("library_type", "user"),
        )
        result = await adapter.export(papers, collection_id=collection_id)
        print(
            "Zotero export stats: "
            f"created={result.get('success_count', 0)}, "
            f"skipped={result.get('skipped_count', 0)}, "
            f"failed={len(result.get('failures', []))}, "
            f"collection={collection_id or 'root'}"
        )
    else:
        print(
            f"Error: unknown format: {args.format}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Exported {len(papers)} papers ({args.format}) -> {args.output}")


async def _handle_enrich(args: argparse.Namespace) -> None:
    papers = _load_papers(args.input)

    use_crossref = args.source in ("crossref", "all")
    use_openalex = args.source in ("openalex", "all")

    semaphore = asyncio.Semaphore(args.concurrency)

    crossref_client = None
    openalex_client = None
    if use_crossref:
        from src.sources.crossref import CrossrefClient

        crossref_client = CrossrefClient()
    if use_openalex:
        from src.sources.openalex import OpenAlexClient

        openalex_client = OpenAlexClient()

    async def _enrich_one(paper: PaperItem) -> PaperItem:
        async with semaphore:
            result = paper

            if use_crossref:
                assert crossref_client is not None
                result = await crossref_client.enrich_paper(result)

            if use_openalex:
                assert openalex_client is not None
                result = await openalex_client.enrich_paper(result)

            return result

    try:
        tasks = [_enrich_one(p) for p in papers]
        results = await asyncio.gather(*tasks)
    finally:
        if crossref_client is not None:
            await crossref_client.close()
        if openalex_client is not None:
            await openalex_client.close()

    final_papers = [p for p in results if p is not None]

    _save_papers(list(final_papers), args.output)

    enriched_count = sum(1 for orig, enr in zip(papers, final_papers) if orig != enr)
    print(f"Enriched {enriched_count}/{len(papers)} papers -> {args.output}")


def _delete_output_dir(output_dir: str) -> None:
    output_dir_path = Path(output_dir)
    removed_any = False
    if output_dir_path.exists() and output_dir_path.is_dir():
        shutil.rmtree(output_dir_path)
        removed_any = True

    # Clean up common intermediate files in cwd (if they exist outside output/)
    intermediate_files = [
        "raw.json",
        "filtered.json",
        "enriched.json",
        "export.json",
        "gmail.json",
        "zotero.json",
    ]
    for filename in intermediate_files:
        candidate = Path(filename)
        if candidate.exists() and candidate.is_file():
            candidate.unlink()
            removed_any = True

    if removed_any:
        print(f"Deleted {output_dir_path} and intermediate files.")
    else:
        print("No output directory or intermediate files to delete.")


async def _handle_delete(args: argparse.Namespace) -> None:
    _delete_output_dir(args.output_dir)


# -------------------- CLI Setup --------------------


def _build_parser() -> argparse.ArgumentParser:
    default_since = (date.today() - timedelta(days=15)).isoformat()
    parser = argparse.ArgumentParser(
        prog="feedder-mcp",
        description="收集、过滤、补充并导出论文（MCP）。",
    )
    subparsers = parser.add_subparsers(
        dest="command", help="可用子命令"
    )

    subparsers.add_parser(
        "serve", help="启动 MCP stdio 服务器（默认）"
    )

    fetch_parser = subparsers.add_parser(
        "fetch", help="从数据源抓取论文"
    )
    fetch_parser.add_argument(
        "-s",
        "--source",
        choices=["rss", "gmail"],
        default="rss",
        help="数据源（默认：rss）",
    )
    fetch_parser.add_argument(
        "--opml",
        "--rss-feeds",
        dest="opml",
        help="OPML 文件路径（RSS 源）",
    )
    fetch_parser.add_argument(
        "-q",
        "--query",
        "--gmail-query",
        dest="query",
        help="Gmail 搜索查询（Gmail 源）",
    )
    fetch_parser.add_argument(
        "-n",
        "--limit",
        "--max-papers",
        dest="limit",
        type=int,
        help="最大抓取数量",
    )
    fetch_parser.add_argument(
        "--since",
        "--from-date",
        dest="since",
        default=default_since,
        help="仅抓取自此日期之后（YYYY-MM-DD，默认近15天）",
    )
    fetch_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="输出 JSON 文件路径",
    )

    filter_parser = subparsers.add_parser(
        "filter", help="按条件过滤论文"
    )
    filter_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="输入 JSON 文件",
    )
    filter_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="输出 JSON 文件路径",
    )
    filter_parser.add_argument(
        "-k",
        "--keywords",
        nargs="+",
        help="关键词（OR 逻辑；未提供则用 RESEARCH_PROMPT 自动生成）",
    )
    filter_parser.add_argument(
        "-x",
        "--exclude",
        "--exclude-keywords",
        dest="exclude",
        nargs="+",
        help="排除关键词（NOT 逻辑）",
    )
    filter_parser.add_argument(
        "-a",
        "--authors",
        nargs="+",
        help="作者过滤（OR 逻辑）",
    )
    filter_parser.add_argument(
        "--min-date",
        "--after",
        "--from",
        dest="min_date",
        help="最早发布日期（YYYY-MM-DD）",
    )
    filter_parser.add_argument(
        "--pdf",
        "--has-pdf",
        "--require-pdf",
        dest="has_pdf",
        action="store_true",
        help="仅保留有 PDF 的论文",
    )
    ai_group = filter_parser.add_mutually_exclusive_group()
    ai_group.add_argument(
        "--ai",
        "--semantic",
        "--use-ai",
        dest="ai",
        action="store_true",
        default=True,
        help="启用 AI 语义过滤（默认开启）",
    )
    ai_group.add_argument(
        "--no-ai",
        dest="ai",
        action="store_false",
        help="禁用 AI 语义过滤",
    )

    export_parser = subparsers.add_parser(
        "export", help="导出论文到指定格式"
    )
    export_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="输入 JSON 文件",
    )
    export_parser.add_argument(
        "-f",
        "--format",
        choices=["json", "zotero"],
        default="json",
        help="导出格式（默认：json）",
    )
    export_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="输出文件路径",
    )
    export_parser.add_argument(
        "--collection",
        "--zotero-collection",
        dest="collection",
        help="Zotero collection key（仅 format=zotero 生效）",
    )
    metadata_group = export_parser.add_mutually_exclusive_group()
    metadata_group.add_argument(
        "-m",
        "--metadata",
        "--include-metadata",
        "--with-metadata",
        dest="include_metadata",
        action="store_true",
        default=True,
        help="包含扩展字段（默认开启）",
    )
    metadata_group.add_argument(
        "--no-metadata",
        dest="include_metadata",
        action="store_false",
        help="导出时去除扩展字段",
    )

    enrich_parser = subparsers.add_parser(
        "enrich",
        help="使用 CrossRef/OpenAlex 补充元数据",
    )
    enrich_parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="输入 JSON 文件",
    )
    enrich_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="输出 JSON 文件路径",
    )
    enrich_parser.add_argument(
        "--api",
        "--source",
        "--provider",
        dest="source",
        choices=["crossref", "openalex", "all"],
        default="all",
        help="补充来源（默认：all）",
    )
    enrich_parser.add_argument(
        "-j",
        "--jobs",
        "--concurrency",
        "--parallel",
        dest="concurrency",
        type=int,
        default=5,
        help="最大并发数（默认：5）",
    )

    delete_parser = subparsers.add_parser(
        "delete",
        help="删除输出目录及中间文件",
    )
    delete_parser.add_argument(
        "--output-dir",
        default="output",
        help="要删除的输出目录（默认：output）",
    )

    return parser


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    parser = _build_parser()
    args = parser.parse_args()

    if not args.command or args.command == "serve":
        try:
            print(
                "提示：已启动 MCP stdio 服务器。"
                "请通过 MCP 客户端连接，或按 Ctrl+C 退出。",
                file=sys.stderr,
            )
            asyncio.run(serve())
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            sys.exit(130)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            logger.debug("Full traceback:", exc_info=True)
            sys.exit(1)
        return

    handlers = {
        "fetch": _handle_fetch,
        "filter": _handle_filter,
        "export": _handle_export,
        "enrich": _handle_enrich,
        "delete": _handle_delete,
    }

    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        asyncio.run(handler(args))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        logger.debug("Full traceback:", exc_info=True)
        sys.exit(1)

