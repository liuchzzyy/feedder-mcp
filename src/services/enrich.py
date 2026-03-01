"""Enrichment service for CrossRef/OpenAlex metadata."""

import asyncio
from typing import Any, Dict, List, Optional

from src.models.responses import PaperItem
from src.sources.crossref import CrossrefClient, CrossrefWork
from src.sources.openalex import OpenAlexClient, OpenAlexWork


class EnrichService:
    """Service for enriching papers with metadata APIs."""

    async def enrich(
        self,
        papers: List[PaperItem],
        provider: str = "all",
        concurrency: int = 5,
    ) -> List[PaperItem]:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if provider not in {"crossref", "openalex", "all"}:
            raise ValueError(
                "provider must be one of: crossref, openalex, all"
            )

        use_crossref = provider in ("crossref", "all")
        use_openalex = provider in ("openalex", "all")

        crossref_client = CrossrefClient() if use_crossref else None
        openalex_client = OpenAlexClient() if use_openalex else None

        semaphore = asyncio.Semaphore(concurrency)

        async def _enrich_one(paper: PaperItem) -> PaperItem:
            async with semaphore:
                result = paper
                if crossref_client is not None:
                    result = await crossref_client.enrich_paper(result)
                if openalex_client is not None:
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

        return [p for p in results if p is not None]

    async def search_crossref(self, title: str) -> List[CrossrefWork]:
        client = CrossrefClient()
        try:
            return await client.search_by_title(title, rows=5)
        finally:
            await client.close()

    async def search_openalex(self, title: str) -> List[OpenAlexWork]:
        client = OpenAlexClient()
        try:
            return await client.search_by_title(title, per_page=5)
        finally:
            await client.close()

    @staticmethod
    def crossref_work_to_dict(work: CrossrefWork) -> Dict[str, Any]:
        return {
            "doi": work.doi,
            "title": work.title,
            "authors": work.authors,
            "journal": work.journal,
            "year": work.year,
            "volume": work.volume,
            "issue": work.issue,
            "pages": work.pages,
            "abstract": work.abstract,
            "url": work.url,
            "publisher": work.publisher,
            "item_type": work.item_type,
            "subjects": work.subjects,
            "funders": work.funders,
            "citation_count": work.citation_count,
            "pdf_url": work.pdf_url,
        }

    @staticmethod
    def openalex_work_to_dict(work: OpenAlexWork) -> Dict[str, Any]:
        paper_id = work.raw_data.get("id") if isinstance(work.raw_data, dict) else None
        pdf_url = None
        publisher = None
        if isinstance(work.raw_data, dict):
            primary_location = work.raw_data.get("primary_location") or {}
            if isinstance(primary_location, dict):
                pdf_url = primary_location.get("pdf_url")
                source = primary_location.get("source") or {}
                if isinstance(source, dict):
                    publisher = source.get("host_organization_name")

        return {
            "id": paper_id,
            "doi": work.doi,
            "title": work.title,
            "authors": work.authors,
            "journal": work.journal,
            "year": work.year,
            "volume": work.volume,
            "issue": work.issue,
            "pages": work.pages,
            "abstract": work.abstract,
            "url": work.url,
            "publisher": publisher,
            "item_type": work.item_type,
            "concepts": work.concepts,
            "cited_by_count": work.cited_by_count,
            "pdf_url": pdf_url,
        }
