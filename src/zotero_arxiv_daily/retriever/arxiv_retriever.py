from .base import BaseRetriever, register_retriever
import arxiv
from arxiv import Result as ArxivResult
from ..protocol import Paper
from ..utils import extract_markdown_from_pdf, extract_tex_code_from_tar
from tempfile import TemporaryDirectory
import feedparser
from tqdm import tqdm
import multiprocessing
import os
from queue import Empty
from typing import Any, Callable, TypeVar
from loguru import logger
import requests
from datetime import datetime, timedelta

T = TypeVar("T")

DOWNLOAD_TIMEOUT = (10, 60)
PDF_EXTRACT_TIMEOUT = 180
TAR_EXTRACT_TIMEOUT = 180


def _download_file(url: str, path: str) -> None:
    with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()
        with open(path, "wb") as file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    file.write(chunk)


def _run_in_subprocess(
    result_queue: Any,
    func: Callable[..., T | None],
    args: tuple[Any, ...],
) -> None:
    try:
        result_queue.put(("ok", func(*args)))
    except Exception as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {exc}"))


def _run_with_hard_timeout(
    func: Callable[..., T | None],
    args: tuple[Any, ...],
    *,
    timeout: float,
    operation: str,
    paper_title: str,
) -> T | None:
    try:
        start_methods = multiprocessing.get_all_start_methods()
        context = multiprocessing.get_context(
            "fork" if "fork" in start_methods else start_methods[0]
        )
        result_queue = context.Queue()
        process = context.Process(
            target=_run_in_subprocess, args=(result_queue, func, args)
        )
        process.start()

        try:
            status, payload = result_queue.get(timeout=timeout)
        except Empty:
            if process.is_alive():
                process.kill()
            process.join(5)
            result_queue.close()
            result_queue.join_thread()
            logger.warning(
                f"{operation} timed out for {paper_title} after {timeout} seconds"
            )
            return None

        process.join(5)
        result_queue.close()
        result_queue.join_thread()

        if status == "ok":
            return payload

        logger.warning(f"{operation} failed for {paper_title}: {payload}")
        return None
    except Exception as exc:
        logger.warning(
            f"{operation} multiprocessing failed for {paper_title}: {exc}. Falling back to direct call."
        )
        try:
            return func(*args)
        except Exception as e:
            logger.warning(f"{operation} failed for {paper_title}: {e}")
            return None


def _extract_text_from_pdf_worker(pdf_url: str) -> str:
    with TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "paper.pdf")
        _download_file(pdf_url, path)
        return extract_markdown_from_pdf(path)


def _extract_text_from_html_worker(html_url: str) -> str | None:
    import trafilatura

    downloaded = trafilatura.fetch_url(html_url)
    if downloaded is None:
        raise ValueError(f"Failed to download HTML from {html_url}")
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
    if not text:
        raise ValueError(f"No text extracted from {html_url}")
    return text


def _extract_text_from_tar_worker(
    source_url: str, paper_id: str, paper_title: str | None = None
) -> str | None:
    with TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "paper.tar.gz")
        _download_file(source_url, path)
        file_contents = extract_tex_code_from_tar(
            path, paper_id, paper_title=paper_title
        )
        if not file_contents or "all" not in file_contents:
            raise ValueError("Main tex file not found.")
        return file_contents["all"]


@register_retriever("arxiv")
class ArxivRetriever(BaseRetriever):
    def __init__(self, config):
        super().__init__(config)
        if self.config.source.arxiv.category is None:
            raise ValueError("category must be specified for arxiv.")

    def _retrieve_raw_papers(self) -> list[ArxivResult]:
        client = arxiv.Client(num_retries=10, delay_seconds=10)
        categories = self.config.source.arxiv.category
        include_cross_list = self.config.source.arxiv.get("include_cross_list", False)
        date_range = self.config.source.arxiv.get("date_range", "1day")

        logger.info(
            f"Fetching arXiv papers: categories={categories}, date_range={date_range}"
        )

        raw_papers = []

        try:
            if date_range == "1day":
                raw_papers = self._fetch_from_rss(
                    client, categories, include_cross_list
                )
            else:
                raw_papers = self._fetch_from_api(client, categories, date_range)
        except Exception as exc:
            logger.error(f"Failed to fetch arXiv papers: {exc}")
            import traceback

            logger.error(traceback.format_exc())
            raise

        logger.info(f"Retrieved {len(raw_papers)} arXiv papers")
        return raw_papers

    def _fetch_from_rss(
        self, client, categories, include_cross_list
    ) -> list[ArxivResult]:
        query = "+".join(categories)
        feed = feedparser.parse(f"https://rss.arxiv.org/atom/{query}")
        if "Feed error for query" in feed.feed.title:
            raise Exception(f"Invalid ARXIV_QUERY: {query}.")
        raw_papers = []
        allowed_announce_types = {"new", "cross"} if include_cross_list else {"new"}
        all_paper_ids = [
            i.id.removeprefix("oai:arXiv.org:")
            for i in feed.entries
            if i.get("arxiv_announce_type", "new") in allowed_announce_types
        ]
        if self.config.executor.debug:
            debug_paper_num = max(
                50, self.config.executor.get("candidate_pool_size", 50)
            )
            all_paper_ids = all_paper_ids[:debug_paper_num]

        bar = tqdm(total=len(all_paper_ids), desc="Fetching arXiv papers")
        for i in range(0, len(all_paper_ids), 20):
            search = arxiv.Search(id_list=all_paper_ids[i : i + 20])
            batch = list(client.results(search))
            bar.update(len(batch))
            raw_papers.extend(batch)
        bar.close()
        return raw_papers

    def _fetch_from_api(self, client, categories, date_range) -> list[ArxivResult]:
        now = datetime.now()
        if date_range == "3days":
            start_date = now - timedelta(days=3)
        elif date_range == "1week":
            start_date = now - timedelta(days=7)
        elif date_range == "1month":
            start_date = now - timedelta(days=30)
        else:
            start_date = now - timedelta(days=1)

        date_str = start_date.strftime("%Y%m%d%H%M%S")
        query_parts = [f"cat:{cat}" for cat in categories]
        query = " OR ".join(query_parts)

        max_results = 200
        if self.config.executor.debug:
            max_results = self.config.executor.get("candidate_pool_size", 50)

        logger.info(
            f"Searching arXiv for papers since {start_date.strftime('%Y-%m-%d')}"
        )

        raw_papers = []
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        bar = tqdm(desc="Fetching arXiv papers")
        for result in client.results(search):
            if result.published.replace(tzinfo=None) < start_date:
                break
            raw_papers.append(result)
            bar.update(1)
            if len(raw_papers) >= max_results:
                break
        bar.close()

        logger.info(f"Found {len(raw_papers)} papers from arXiv API")
        return raw_papers

    def convert_to_paper(self, raw_paper: ArxivResult) -> Paper:
        title = raw_paper.title
        authors = [a.name for a in raw_paper.authors]
        abstract = raw_paper.summary
        pdf_url = raw_paper.pdf_url
        full_text = extract_text_from_tar(raw_paper)
        if full_text is None:
            full_text = extract_text_from_html(raw_paper)
        if full_text is None:
            full_text = extract_text_from_pdf(raw_paper)

        weight = self.retriever_config.get("weight", 1.5)

        paper = Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=raw_paper.entry_id,
            pdf_url=pdf_url,
            full_text=full_text,
        )

        paper.metadata["primary_source"] = "arxiv"
        paper.metadata["source_weight"] = weight

        return paper


def extract_text_from_html(paper: ArxivResult) -> str | None:
    html_url = paper.entry_id.replace("/abs/", "/html/")
    try:
        return _extract_text_from_html_worker(html_url)
    except Exception as exc:
        logger.warning(f"HTML extraction failed for {paper.title}: {exc}")
        return None


def extract_text_from_pdf(paper: ArxivResult) -> str | None:
    if paper.pdf_url is None:
        logger.warning(f"No PDF URL available for {paper.title}")
        return None
    return _run_with_hard_timeout(
        _extract_text_from_pdf_worker,
        (paper.pdf_url,),
        timeout=PDF_EXTRACT_TIMEOUT,
        operation="PDF extraction",
        paper_title=paper.title,
    )


def extract_text_from_tar(paper: ArxivResult) -> str | None:
    source_url = paper.source_url()
    if source_url is None:
        logger.warning(f"No source URL available for {paper.title}")
        return None
    return _run_with_hard_timeout(
        _extract_text_from_tar_worker,
        (source_url, paper.entry_id, paper.title),
        timeout=TAR_EXTRACT_TIMEOUT,
        operation="Tar extraction",
        paper_title=paper.title,
    )
