from .base import BaseRetriever, register_retriever
from ..protocol import Paper
from datetime import datetime, timedelta
import requests
from tqdm import tqdm
from loguru import logger
from time import sleep

OPENREVIEW_API = "https://api2.openreview.net/notes"
REQUEST_TIMEOUT = 30


@register_retriever("openreview")
class OpenReviewRetriever(BaseRetriever):
    def __init__(self, config):
        super().__init__(config)
        self.conferences = self.retriever_config.get(
            "conferences", ["ICLR 2026", "NeurIPS 2025"]
        )
        self.status = self.retriever_config.get("status", "accepted")
        self.max_results = self.retriever_config.get("max_results", 50)
        self.weight = self.retriever_config.get("weight", 1.0)
        self.enabled = self.retriever_config.get("enabled", True)

    def _retrieve_raw_papers(self) -> list[dict]:
        if not self.enabled:
            logger.info("OpenReview retriever is disabled")
            return []

        logger.info(f"Fetching OpenReview papers from conferences: {self.conferences}")

        all_papers = []

        for conference in self.conferences:
            try:
                papers = self._fetch_conference_papers(conference)
                all_papers.extend(papers)
            except Exception as e:
                logger.warning(f"Failed to fetch papers from {conference}: {e}")
                continue

        result = all_papers[: self.max_results]
        logger.info(f"OpenReview returned {len(result)} papers")
        return result

    def _fetch_conference_papers(self, conference: str) -> list[dict]:
        params = {
            "content.venueid": conference,
            "details": "replyCount,writable",
            "limit": 100,
        }

        if self.status == "accepted":
            params["invitation"] = f"{conference}/-/Blind_Submission"

        try:
            response = requests.get(
                OPENREVIEW_API, params=params, timeout=REQUEST_TIMEOUT
            )
            response.raise_for_status()
            data = response.json()

            notes = data.get("notes", [])
            return notes

        except Exception as e:
            logger.warning(f"OpenReview API error for {conference}: {e}")
            return []

    def convert_to_paper(self, raw_paper: dict) -> Paper | None:
        try:
            content = raw_paper.get("content", {})

            title = content.get("title", "")
            if isinstance(title, list):
                title = title[0] if title else ""
            if not title:
                return None

            authors = content.get("authors", [])
            if isinstance(authors, str):
                authors = [authors]

            abstract = content.get("abstract", "")
            if isinstance(abstract, list):
                abstract = abstract[0] if abstract else ""

            venue = raw_paper.get("content", {}).get("venue", "")
            if isinstance(venue, list):
                venue = venue[0] if venue else ""

            paper_id = raw_paper.get("id", "")
            url = f"https://openreview.net/forum?id={paper_id}" if paper_id else ""

            pdf_url = None
            if paper_id:
                pdf_url = f"https://openreview.net/pdf?id={paper_id}"

            paper = Paper(
                source=self.name,
                title=title,
                authors=authors,
                abstract=abstract,
                url=url,
                pdf_url=pdf_url,
                doi=None,
                full_text=None,
            )

            paper.metadata["source_weight"] = self.weight
            paper.metadata["primary_source"] = "openreview"
            paper.metadata["openreview_id"] = paper_id
            paper.metadata["venue"] = venue

            cdate = raw_paper.get("cdate", None)
            if cdate:
                try:
                    paper.published_date = datetime.fromtimestamp(cdate / 1000)
                except:
                    pass

            return paper

        except Exception as e:
            logger.warning(f"Failed to convert OpenReview paper: {e}")
            return None
