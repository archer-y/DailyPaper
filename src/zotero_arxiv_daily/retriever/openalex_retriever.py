from .base import BaseRetriever, register_retriever
from ..protocol import Paper
from datetime import datetime, timedelta
import requests
from tqdm import tqdm
from loguru import logger
from time import sleep

OPENALEX_API = "https://api.openalex.org/works"
REQUEST_TIMEOUT = 30


@register_retriever("openalex")
class OpenAlexRetriever(BaseRetriever):
    def __init__(self, config):
        super().__init__(config)
        self.keywords = self.retriever_config.get("keywords", [])
        self.date_range = self.retriever_config.get("date_range", "1day")
        self.max_results = self.retriever_config.get("max_results", 100)
        self.enabled = self.retriever_config.get("enabled", True)
        if not self.keywords:
            logger.warning("No keywords configured for OpenAlex retriever")

    def _get_date_filter(self) -> str:
        now = datetime.now()
        if self.date_range == "1day":
            start_date = now - timedelta(days=1)
        elif self.date_range == "3days":
            start_date = now - timedelta(days=3)
        elif self.date_range == "1week":
            start_date = now - timedelta(days=7)
        elif self.date_range == "1month":
            start_date = now - timedelta(days=30)
        else:
            start_date = now - timedelta(days=1)
        return f"from_publication_date:{start_date.strftime('%Y-%m-%d')}"

    def _retrieve_raw_papers(self) -> list[dict]:
        if not self.enabled:
            logger.info("OpenAlex retriever is disabled")
            return []

        raw_papers = []
        date_filter = self._get_date_filter()
        keywords_query = " OR ".join(self.keywords)
        filter_query = f"{date_filter},title.search:{keywords_query}"
        
        params = {
            "filter": filter_query,
            "per_page": min(self.max_results, 200),
            "sort": "publication_date:desc",
        }
        
        logger.info(f"Querying OpenAlex with keywords: {keywords_query}, date: {date_filter}")
        
        try:
            response = requests.get(OPENALEX_API, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            logger.info(f"OpenAlex returned {len(results)} papers")
            return results
        except Exception as e:
            logger.warning(f"OpenAlex API request failed: {e}")
            return []

    def convert_to_paper(self, raw_paper: dict) -> Paper | None:
        try:
            title = raw_paper.get("title", "")
            if not title:
                return None
            
            authors = []
            authorships = raw_paper.get("authorships", [])
            for authorship in authorships:
                author = authorship.get("author", {})
                if author and author.get("display_name"):
                    authors.append(author["display_name"])
            
            abstract = raw_paper.get("abstract_inverted_index", None)
            if abstract:
                abstract_text = self._reconstruct_abstract(abstract)
            else:
                abstract_text = ""
            
            doi = raw_paper.get("doi", None)
            url = raw_paper.get("id", "")
            
            pdf_url = None
            oa = raw_paper.get("open_access", {})
            if oa.get("is_oa"):
                pdf_url = oa.get("oa_url")
            
            locations = raw_paper.get("primary_location", {})
            if locations:
                source = locations.get("source", {})
                if source:
                    landing_page = locations.get("landing_page_url", "")
                    if landing_page:
                        url = landing_page
            
            return Paper(
                source=self.name,
                title=title,
                authors=authors,
                abstract=abstract_text,
                url=url,
                pdf_url=pdf_url,
                doi=doi,
                full_text=None,
            )
        except Exception as e:
            logger.warning(f"Failed to convert OpenAlex paper: {e}")
            return None

    def _reconstruct_abstract(self, inverted_index: dict) -> str:
        if not inverted_index:
            return ""
        positions = []
        for word, pos_list in inverted_index.items():
            for pos in pos_list:
                positions.append((pos, word))
        positions.sort(key=lambda x: x[0])
        return " ".join([word for _, word in positions])