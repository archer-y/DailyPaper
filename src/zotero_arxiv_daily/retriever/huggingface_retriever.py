from .base import BaseRetriever, register_retriever
from ..protocol import Paper
from datetime import datetime, timedelta
import requests
from tqdm import tqdm
from loguru import logger
from time import sleep

HF_PAPERS_API = "https://huggingface.co/api/daily_papers"
REQUEST_TIMEOUT = 30


@register_retriever("huggingface")
class HuggingFaceRetriever(BaseRetriever):
    def __init__(self, config):
        super().__init__(config)
        self.max_results = self.retriever_config.get("max_results", 50)
        self.date_range = self.retriever_config.get("date_range", "1day")
        self.weight = self.retriever_config.get("weight", 1.2)
        self.enabled = self.retriever_config.get("enabled", True)

    def _retrieve_raw_papers(self) -> list[dict]:
        if not self.enabled:
            logger.info("HuggingFace retriever is disabled")
            return []

        logger.info("Fetching HuggingFace daily papers...")

        try:
            response = requests.get(HF_PAPERS_API, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            papers = response.json()

            if not isinstance(papers, list):
                logger.warning(
                    f"Unexpected HuggingFace response format: {type(papers)}"
                )
                return []

            date_cutoff = self._get_date_cutoff()
            filtered = []

            for paper in papers:
                published = paper.get("publishedAt")
                if published:
                    pub_date = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    if pub_date.replace(tzinfo=None) >= date_cutoff:
                        filtered.append(paper)
                else:
                    filtered.append(paper)

            result = filtered[: self.max_results]
            logger.info(f"HuggingFace returned {len(result)} papers")
            return result

        except Exception as e:
            logger.warning(f"HuggingFace API request failed: {e}")
            return []

    def _get_date_cutoff(self) -> datetime:
        now = datetime.now()
        range_map = {
            "1day": 1,
            "3days": 3,
            "1week": 7,
            "1month": 30,
        }
        days = range_map.get(self.date_range, 1)
        return now - timedelta(days=days)

    def convert_to_paper(self, raw_paper: dict) -> Paper | None:
        try:
            title = raw_paper.get("title", "")
            if not title:
                return None

            authors = []
            paper_authors = raw_paper.get("authors", [])
            for author in paper_authors:
                if isinstance(author, dict):
                    name = author.get("name", "")
                else:
                    name = str(author)
                if name:
                    authors.append(name)

            abstract = raw_paper.get("paper", {}).get("summary", "")
            if not abstract:
                abstract = raw_paper.get("summary", "")

            arxiv_id = raw_paper.get("paper", {}).get("id", "")
            if not arxiv_id:
                arxiv_id = raw_paper.get("arxiv_id", "")

            url = (
                f"https://huggingface.co/papers/{arxiv_id}"
                if arxiv_id
                else raw_paper.get("url", "")
            )
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None

            upvotes = raw_paper.get("paper", {}).get("upvotes", 0)
            if not upvotes:
                upvotes = raw_paper.get("upvotes", 0)

            published_date = None
            published_at = raw_paper.get("publishedAt")
            if published_at:
                try:
                    published_date = datetime.fromisoformat(
                        published_at.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except:
                    pass

            paper = Paper(
                source=self.name,
                title=title,
                authors=authors,
                abstract=abstract,
                url=url,
                pdf_url=pdf_url,
                doi=raw_paper.get("doi"),
                full_text=None,
                published_date=published_date,
            )

            paper.metadata["source_weight"] = self.weight
            paper.metadata["primary_source"] = "huggingface"
            paper.metadata["hf_upvotes"] = upvotes
            paper.metadata["arxiv_id"] = arxiv_id if arxiv_id else None

            return paper

        except Exception as e:
            logger.warning(f"Failed to convert HuggingFace paper: {e}")
            return None
