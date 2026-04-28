from .enrichment import apply_keyword_boost, deduplicate_papers, enrich_papers, prefilter_papers_with_code, parallel_filter
from .protocol import CorpusPaper, Paper
import os
from openai import OpenAI
from loguru import logger
from pyzotero import zotero
from omegaconf import DictConfig, ListConfig, OmegaConf
from .utils import glob_match
from .retriever import get_retriever_cls
from .reranker import get_reranker_cls
from tqdm import tqdm
import random
from datetime import datetime
from .enrichment import apply_keyword_boost, deduplicate_papers, enrich_papers
from .notifier import send_notifications
from .reporting import write_outputs
from .utils import send_email
from .construct_email import render_email


def normalize_path_patterns(patterns: list[str] | ListConfig | None, config_key: str) -> list[str] | None:
    if patterns is None:
        return None

    if not isinstance(patterns, (list, ListConfig)):
        raise TypeError(
            f"config.zotero.{config_key} must be a list of glob patterns or null, "
            'for example ["2026/survey/**"]. Single strings are not supported.'
        )

    if any(not isinstance(pattern, str) for pattern in patterns):
        raise TypeError(f"config.zotero.{config_key} must contain only glob pattern strings.")

    return list(patterns)


class Executor:
    def __init__(self, config:DictConfig):
        self.config = config
        
        # Force read from environment variables
        zotero_id = os.getenv("ZOTERO_ID")
        zotero_key = os.getenv("ZOTERO_KEY")
        
        if zotero_id:
            OmegaConf.set_struct(config, False)
            config.zotero.user_id = zotero_id
            OmegaConf.set_struct(config, True)
            logger.info(f"ZOTERO_ID loaded from environment: {zotero_id}")
        else:
            logger.error("ZOTERO_ID not found in environment variables")
        
        if zotero_key:
            OmegaConf.set_struct(config, False)
            config.zotero.api_key = zotero_key
            OmegaConf.set_struct(config, True)
            logger.info("ZOTERO_KEY loaded from environment")
        else:
            logger.error("ZOTERO_KEY not found in environment variables")
        
        openai_key = os.getenv("OPENAI_API_KEY")
        openai_base_url = os.getenv("OPENAI_BASE_URL")
        
        if openai_key:
            OmegaConf.set_struct(config, False)
            config.llm.api.key = openai_key
            OmegaConf.set_struct(config, True)
            logger.info("OPENAI_API_KEY loaded from environment")
        
        if openai_base_url:
            OmegaConf.set_struct(config, False)
            config.llm.api.base_url = openai_base_url
            OmegaConf.set_struct(config, True)
            logger.info(f"OPENAI_BASE_URL loaded from environment: {openai_base_url}")
        
        self.include_path_patterns = normalize_path_patterns(config.zotero.include_path, "include_path")
        self.ignore_path_patterns = normalize_path_patterns(config.zotero.ignore_path, "ignore_path")
        self.retrievers = {
            source: get_retriever_cls(source)(config) for source in config.executor.source
        }
        self.reranker = get_reranker_cls(config.executor.reranker)(config)
        self.openai_client = OpenAI(api_key=config.llm.api.key, base_url=config.llm.api.base_url)
    def fetch_zotero_corpus(self) -> list[CorpusPaper]:
        # Check if Zotero is enabled
        zotero_enabled = self.config.zotero.get("enabled", True)
        if not zotero_enabled:
            logger.info("Zotero is disabled, skipping corpus fetch")
            return []
        
        logger.info("Fetching zotero corpus")
        
        # Verify credentials before connecting
        user_id = self.config.zotero.user_id
        api_key = self.config.zotero.api_key
        
        if not user_id or not api_key:
            logger.warning("Zotero credentials not configured. Skipping Zotero corpus fetch.")
            logger.warning("Set ZOTERO_ID and ZOTERO_KEY environment variables to enable Zotero integration.")
            return []
        
        logger.info(f"Connecting to Zotero with user_id: {user_id}")
        zot = zotero.Zotero(user_id, 'user', api_key)
        collections = zot.everything(zot.collections())
        collections = {c['key']:c for c in collections}
        corpus = zot.everything(zot.items(itemType='conferencePaper || journalArticle || preprint'))
        corpus = [c for c in corpus if c['data']['abstractNote'] != '']
        def get_collection_path(col_key:str) -> str:
            if p := collections[col_key]['data']['parentCollection']:
                return get_collection_path(p) + '/' + collections[col_key]['data']['name']
            else:
                return collections[col_key]['data']['name']
        for c in corpus:
            paths = [get_collection_path(col) for col in c['data']['collections']]
            c['paths'] = paths
        logger.info(f"Fetched {len(corpus)} zotero papers")
        return [CorpusPaper(
            title=c['data']['title'],
            abstract=c['data']['abstractNote'],
            added_date=datetime.strptime(c['data']['dateAdded'], '%Y-%m-%dT%H:%M:%SZ'),
            paths=c['paths']
        ) for c in corpus]
    
    def filter_corpus(self, corpus:list[CorpusPaper]) -> list[CorpusPaper]:
        if self.include_path_patterns:
            logger.info(f"Selecting zotero papers matching include_path: {self.include_path_patterns}")
            corpus = [
                c for c in corpus
                if any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.include_path_patterns
                )
            ]
        if self.ignore_path_patterns:
            logger.info(f"Excluding zotero papers matching ignore_path: {self.ignore_path_patterns}")
            corpus = [
                c for c in corpus
                if not any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.ignore_path_patterns
                )
            ]
        if self.include_path_patterns or self.ignore_path_patterns:
            samples = random.sample(corpus, min(5, len(corpus)))
            samples = '\n'.join([c.title + ' - ' + '\n'.join(c.paths) for c in samples])
            logger.info(f"Selected {len(corpus)} zotero papers:\n{samples}\n...")
        return corpus

    
    def run(self):
        corpus = self.fetch_zotero_corpus()
        corpus = self.filter_corpus(corpus)
        
        # Allow running without Zotero corpus (keyword-only mode)
        if len(corpus) == 0:
            logger.warning("No zotero papers found. Running in keyword-only mode.")
            logger.warning("To enable similarity matching, configure Zotero credentials.")
        
        all_papers = []
        source_errors = {}
        for source, retriever in self.retrievers.items():
            logger.info(f"Retrieving {source} papers...")
            try:
                papers = retriever.retrieve_papers()
            except Exception as exc:
                source_errors[source] = str(exc)
                logger.warning(f"Failed to retrieve {source} papers: {exc}")
                continue
            if len(papers) == 0:
                logger.info(f"No {source} papers found")
                continue
            logger.info(f"Retrieved {len(papers)} {source} papers")
            all_papers.extend(papers)
        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")
        all_papers = deduplicate_papers(all_papers)
        logger.info(f"Total {len(all_papers)} papers after deduplication")
        reranked_papers = []
        if len(all_papers) > 0:
            logger.info("Reranking papers...")
            reranked_papers = self.reranker.rerank(all_papers, corpus)
            
            filter_mode = self.config.executor.get("filter_mode", "serial")
            keywords = self.config.executor.get("keywords", [])
            keyword_weight = float(self.config.executor.get("keyword_score_weight", 0.0))
            similarity_threshold = float(self.config.executor.get("similarity_threshold", 2.0))
            
            if filter_mode == "parallel":
                logger.info(f"Using parallel filter mode (keyword OR similarity>={similarity_threshold})")
                reranked_papers = apply_keyword_boost(reranked_papers, keywords, keyword_weight)
                candidate_count = min(len(reranked_papers), self.config.executor.get("candidate_pool_size", 50))
                reranked_papers = parallel_filter(
                    reranked_papers[:candidate_count],
                    keywords,
                    similarity_threshold
                )
            else:
                reranked_papers = apply_keyword_boost(reranked_papers, keywords, keyword_weight)
                min_code_ratio = float(self.config.executor.get("min_papers_with_code_ratio", 0.0))
                if min_code_ratio > 0:
                    candidate_count = min(len(reranked_papers), self.config.executor.get("code_filter_candidates", 50))
                    reranked_papers = prefilter_papers_with_code(reranked_papers[:candidate_count], min_code_ratio)
            
            reranked_papers = reranked_papers[:self.config.executor.max_paper_num]
            logger.info("Generating TLDR and affiliations...")
            for p in tqdm(reranked_papers):
                p.generate_tldr(self.openai_client, self.config.llm)
                p.generate_affiliations(self.openai_client, self.config.llm)
        elif not self.config.executor.send_empty:
            logger.info("No new papers found. Notifications will be skipped.")

        logger.info("Enriching paper metadata...")
        enrichment_failures = enrich_papers(reranked_papers, self.config.enrichment)
        if source_errors:
            enrichment_failures["retrievers"] = [f"{name}: {error}" for name, error in source_errors.items()]

        if self.config.reporting.enabled:
            logger.info("Writing Markdown and JSON reports...")
            markdown_path, json_path = write_outputs(reranked_papers, self.config.reporting, enrichment_failures)
            logger.info(f"Wrote reports: {markdown_path}, {json_path}")
            if reranked_papers or self.config.executor.send_empty:
                send_notifications(self.config.notifications, markdown_path)

        if self.config.email.get("enabled", False) and (reranked_papers or self.config.executor.send_empty):
            logger.info("Sending email...")
            email_content = render_email(reranked_papers)
            send_email(self.config, email_content)
            logger.info("Email sent successfully")
