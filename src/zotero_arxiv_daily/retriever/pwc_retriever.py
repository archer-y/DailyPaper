from .base import BaseRetriever, register_retriever
from ..protocol import Paper
from datetime import datetime, timedelta
import requests
from tqdm import tqdm
from loguru import logger
from time import sleep

PWC_API = "https://paperswithcode.com/api/v1/papers"
REQUEST_TIMEOUT = 30


@register_retriever("pwc")
class PWCRetriever(BaseRetriever):
    def __init__(self, config):
        super().__init__(config)
        self.areas = self.retriever_config.get(
            "areas", ["Artificial Intelligence", "Machine Learning"]
        )
        self.require_code = self.retriever_config.get("require_code", True)
        self.max_results = self.retriever_config.get("max_results", 50)
        self.weight = self.retriever_config.get("weight", 1.0)
        self.enabled = self.retriever_config.get("enabled", True)

    def _retrieve_raw_papers(self) -> list[dict]:
        if not self.enabled:
            logger.info("PWC retriever is disabled")
            return []

        logger.info(f"Fetching PWC papers from areas: {self.areas}")

        all_papers = []

        for area in self.areas:
            try:
                papers = self._fetch_area_papers(area)
                all_papers.extend(papers)
            except Exception as e:
                logger.warning(f"Failed to fetch PWC papers from {area}: {e}")
                continue

        seen_ids = set()
        unique_papers = []
        for paper in all_papers:
            paper_id = paper.get("id")
            if paper_id and paper_id not in seen_ids:
                seen_ids.add(paper_id)
                unique_papers.append(paper)

        if self.require_code:
            unique_papers = [p for p in unique_papers if p.get("has_code", False)]

        result = unique_papers[: self.max_results]
        logger.info(f"PWC returned {len(result)} papers")
        return result

    def _fetch_area_papers(self, area: str) -> list[dict]:
        params = {
            "area": area,
            "ordering": "-date_publication",
            "page": 1,
            "items_per_page": 50,
        }

        papers = []

        try:
            response = requests.get(PWC_API, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            papers.extend(results)

        except Exception as e:
            logger.warning(f"PWC API error for area {area}: {e}")

        return papers

    def convert_to_paper(self, raw_paper: dict) -> Paper | None:
        try:
            title = raw_paper.get("title", "")
            if not title:
                return None

            authors = raw_paper.get("authors", [])
            if isinstance(authors, str):
                authors = [authors]

            abstract = raw_paper.get("abstract", "")

            url = raw_paper.get("url", "") or raw_paper.get("paper_url", "")
            pdf_url = raw_paper.get("pdf_url", "")

            arxiv_id = raw_paper.get("arxiv_id", "")
            doi = raw_paper.get("doi", "")

            github_url = raw_paper.get("github_url", "")
            code_urls = [github_url] if github_url else []

            paper = Paper(
                source=self.name,
                title=title,
                authors=authors,
                abstract=abstract,
                url=url,
                pdf_url=pdf_url,
                doi=doi if doi else None,
                full_text=None,
            )

            paper.metadata["source_weight"] = self.weight
            paper.metadata["primary_source"] = "pwc"
            paper.metadata["arxiv_id"] = arxiv_id if arxiv_id else None
            paper.code_urls = code_urls
            paper.project_urls = code_urls

            stars = raw_paper.get("stars", 0)
            if stars:
                paper.metadata["github_stars"] = stars

            return paper

        except Exception as e:
            logger.warning(f"Failed to convert PWC paper: {e}")
            return None
