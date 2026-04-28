from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Iterable

import requests
from loguru import logger

from .protocol import Paper

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")
REQUEST_TIMEOUT = 12


def extract_arxiv_id(paper: Paper) -> str | None:
    for value in (paper.url, paper.pdf_url):
        if not value:
            continue
        match = ARXIV_ID_RE.search(value)
        if match:
            return match.group(1)
    return None


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()


def deduplicate_papers(
    papers: Iterable[Paper], title_threshold: float = 0.96
) -> list[Paper]:
    """Deduplicate papers by arxiv_id, DOI, and similar titles.

    For multi-source papers, preserve the one with higher source_weight.
    """
    from difflib import SequenceMatcher
    from loguru import logger

    papers_list = list(papers)
    kept: list[Paper] = []
    seen_ids: set[str] = set()
    seen_dois: set[str] = set()
    seen_titles: list[str] = []

    # Sort by source weight first (higher weight = primary source)
    papers_sorted = sorted(
        papers_list, key=lambda p: p.metadata.get("source_weight", 1.0), reverse=True
    )

    for paper in papers_sorted:
        arxiv_id = extract_arxiv_id(paper)
        doi = (paper.doi or "").lower()
        title = normalize_title(paper.title)

        if arxiv_id and arxiv_id in seen_ids:
            # Merge metadata from duplicate
            _merge_duplicate_metadata(kept, paper, arxiv_id)
            continue
        if doi and doi in seen_dois:
            continue
        if title and any(
            SequenceMatcher(None, title, existing).ratio() >= title_threshold
            for existing in seen_titles
        ):
            continue

        if arxiv_id:
            seen_ids.add(arxiv_id)
        if doi:
            seen_dois.add(doi)
        if title:
            seen_titles.append(title)
        kept.append(paper)

    logger.info(f"Deduplicated {len(papers_list)} papers to {len(kept)}")
    return kept


def _merge_duplicate_metadata(
    papers: list[Paper], duplicate: Paper, arxiv_id: str
) -> None:
    """Merge metadata from duplicate paper into existing one."""
    for paper in papers:
        if extract_arxiv_id(paper) == arxiv_id:
            # Track all sources that found this paper
            sources = paper.metadata.get("sources", [])
            dup_source = duplicate.metadata.get("primary_source", "unknown")
            if dup_source not in sources:
                sources.append(dup_source)
                paper.metadata["sources"] = sources

            # Merge code URLs
            for url in duplicate.code_urls:
                if url and url not in paper.code_urls:
                    paper.code_urls.append(url)

            # Merge project URLs
            for url in duplicate.project_urls:
                if url and url not in paper.project_urls:
                    paper.project_urls.append(url)

            # Merge other useful metadata
            if duplicate.metadata.get("hf_upvotes"):
                paper.metadata["hf_upvotes"] = duplicate.metadata["hf_upvotes"]
            if duplicate.metadata.get("github_stars"):
                paper.metadata["github_stars"] = duplicate.metadata["github_stars"]

            break


def weighted_sort_papers(papers: list[Paper]) -> list[Paper]:
    """Sort papers by weighted score (source_weight * paper_score)."""
    from loguru import logger

    for paper in papers:
        source_weight = paper.metadata.get("source_weight", 1.0)
        paper_score = paper.score if paper.score is not None else 0

        # Weighted score
        paper.metadata["weighted_score"] = paper_score * source_weight

    sorted_papers = sorted(
        papers, key=lambda p: p.metadata.get("weighted_score", 0), reverse=True
    )

    logger.info(f"Sorted {len(papers)} papers by weighted score")
    return sorted_papers


def ensure_source_diversity(
    papers: list[Paper], max_per_source: int = 5, min_pwc_ratio: float = 0.0
) -> list[Paper]:
    """Ensure source diversity and minimum PWC ratio.

    Args:
        papers: List of papers sorted by score
        max_per_source: Maximum papers from each source
        min_pwc_ratio: Minimum ratio of papers from PWC (0.0-1.0)
    """
    from loguru import logger

    if min_pwc_ratio > 0:
        return ensure_source_diversity_with_pwc_ratio(
            papers, max_per_source, min_pwc_ratio
        )

    source_counts: dict[str, int] = {}
    diversified: list[Paper] = []

    for paper in papers:
        source = paper.metadata.get("primary_source", "unknown")

        if source_counts.get(source, 0) < max_per_source:
            diversified.append(paper)
            source_counts[source] = source_counts.get(source, 0) + 1

    logger.info(f"Source diversity: {source_counts}")
    return diversified


def ensure_source_diversity_with_pwc_ratio(
    papers: list[Paper], max_per_source: int, min_pwc_ratio: float
) -> list[Paper]:
    """Ensure minimum PWC ratio while maintaining source diversity.

    Strategy:
    1. First, select required minimum PWC papers
    2. Then, fill remaining slots with other sources (max_per_source each)
    3. Finally, fill any remaining slots with highest-scoring papers
    """
    from loguru import logger

    total_needed = len(papers)
    min_pwc_count = max(1, int(total_needed * min_pwc_ratio))

    pwc_papers = [p for p in papers if p.metadata.get("primary_source") == "pwc"]
    other_papers = [p for p in papers if p.metadata.get("primary_source") != "pwc"]

    diversified: list[Paper] = []
    source_counts: dict[str, int] = {}

    # Step 1: Add minimum PWC papers first
    pwc_added = 0
    for paper in pwc_papers:
        if pwc_added < min_pwc_count:
            diversified.append(paper)
            source_counts["pwc"] = source_counts.get("pwc", 0) + 1
            pwc_added += 1

    # Step 2: Add other papers respecting max_per_source
    for paper in other_papers:
        source = paper.metadata.get("primary_source", "unknown")
        if source_counts.get(source, 0) < max_per_source:
            diversified.append(paper)
            source_counts[source] = source_counts.get(source, 0) + 1

    # Step 3: If we still need more PWC papers, add them
    if pwc_added < min_pwc_count:
        for paper in pwc_papers[pwc_added:]:
            if paper not in diversified:
                diversified.append(paper)
                source_counts["pwc"] = source_counts.get("pwc", 0) + 1
                pwc_added += 1
                if pwc_added >= min_pwc_count:
                    break

    # Step 4: Fill remaining slots with highest-scoring papers not yet included
    included_ids = {id(p) for p in diversified}
    for paper in papers:
        if id(paper) not in included_ids:
            source = paper.metadata.get("primary_source", "unknown")
            if source_counts.get(source, 0) < max_per_source:
                diversified.append(paper)
                source_counts[source] = source_counts.get(source, 0) + 1
                included_ids.add(id(paper))

    # Sort by score
    diversified.sort(key=lambda p: p.metadata.get("weighted_score", 0), reverse=True)

    logger.info(f"Source diversity: {source_counts}")
    logger.info(
        f"PWC papers: {source_counts.get('pwc', 0)}/{len(diversified)} ({source_counts.get('pwc', 0) / max(len(diversified), 1):.0%})"
    )

    return diversified


def apply_keyword_boost(
    papers: list[Paper], keywords: Iterable[str], weight: float
) -> list[Paper]:
    cleaned = [k.lower() for k in keywords if k]
    if not cleaned or weight <= 0:
        return papers

    for paper in papers:
        haystack = f"{paper.title}\n{paper.abstract}".lower()
        matches = sum(1 for keyword in cleaned if keyword in haystack)
        if matches and paper.score is not None:
            paper.score += matches * weight
            paper.metadata["keyword_matches"] = matches
    return sorted(
        papers, key=lambda p: p.score if p.score is not None else -1, reverse=True
    )


def apply_keyword_match(
    papers: list[Paper], keywords: Iterable[str]
) -> list[tuple[Paper, bool]]:
    """Check if each paper matches any keyword.

    Returns a list of (paper, has_keyword_match) tuples.
    """
    cleaned = [k.lower() for k in keywords if k]
    if not cleaned:
        return [(p, False) for p in papers]

    results = []
    for paper in papers:
        haystack = f"{paper.title}\n{paper.abstract}".lower()
        has_match = any(keyword in haystack for keyword in cleaned)
        if has_match:
            matches = sum(1 for keyword in cleaned if keyword in haystack)
            paper.metadata["keyword_matches"] = matches
        results.append((paper, has_match))
    return results


def apply_similarity_threshold(
    papers: list[Paper], threshold: float
) -> list[tuple[Paper, bool]]:
    """Check if each paper's similarity score meets the threshold.

    Returns a list of (paper, meets_threshold) tuples.
    """
    results = []
    for paper in papers:
        score = paper.score if paper.score is not None else 0
        meets = score >= threshold
        results.append((paper, meets))
    return results


def parallel_filter(
    papers: list[Paper],
    keywords: Iterable[str],
    similarity_threshold: float,
) -> list[Paper]:
    """Filter papers using parallel independent criteria.

    A paper passes the filter if it matches ANY of:
    - Contains at least one keyword
    - Similarity score >= threshold

    Returns filtered and sorted papers.
    """
    from loguru import logger

    if not papers:
        return papers

    keyword_results = apply_keyword_match(papers, keywords)
    similarity_results = apply_similarity_threshold(papers, similarity_threshold)

    filtered = []
    keyword_match_count = 0
    similarity_match_count = 0
    both_match_count = 0

    for i, paper in enumerate(papers):
        has_keyword = keyword_results[i][1]
        meets_similarity = similarity_results[i][1]

        if has_keyword or meets_similarity:
            filtered.append(paper)
            if has_keyword and meets_similarity:
                both_match_count += 1
            elif has_keyword:
                keyword_match_count += 1
            else:
                similarity_match_count += 1

    logger.info(
        f"Parallel filter: {len(filtered)}/{len(papers)} papers passed "
        f"(keyword: {keyword_match_count}, similarity: {similarity_match_count}, both: {both_match_count})"
    )

    filtered.sort(key=lambda p: p.score if p.score is not None else -1, reverse=True)
    return filtered


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict | list | None:
    response = requests.get(url, headers=headers or {}, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _merge_links(paper: Paper, links: Iterable[str | None], *, kind: str) -> None:
    target = paper.code_urls if kind == "code" else paper.project_urls
    for link in links:
        if link and link not in target:
            target.append(link)


def enrich_with_semantic_scholar(paper: Paper, api_key: str | None) -> None:
    arxiv_id = extract_arxiv_id(paper)
    if not arxiv_id:
        return

    fields = ",".join(
        [
            "title",
            "url",
            "citationCount",
            "referenceCount",
            "influentialCitationCount",
            "publicationDate",
            "tldr",
            "openAccessPdf",
            "externalIds",
            "authors",
        ]
    )
    headers = {"x-api-key": api_key} if api_key else None
    data = _get_json(
        f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}?fields={fields}",
        headers=headers,
    )
    if not isinstance(data, dict):
        return

    external_ids = data.get("externalIds") or {}
    paper.doi = paper.doi or external_ids.get("DOI")
    paper.metadata["semantic_scholar"] = {
        "paper_id": data.get("paperId"),
        "url": data.get("url"),
        "citation_count": data.get("citationCount"),
        "reference_count": data.get("referenceCount"),
        "influential_citation_count": data.get("influentialCitationCount"),
        "publication_date": data.get("publicationDate"),
        "tldr": (data.get("tldr") or {}).get("text")
        if isinstance(data.get("tldr"), dict)
        else None,
    }


def enrich_with_hugging_face(paper: Paper) -> None:
    arxiv_id = extract_arxiv_id(paper)
    if not arxiv_id:
        return

    paper_data = _get_json(f"https://huggingface.co/api/papers/{arxiv_id}")
    if isinstance(paper_data, dict):
        paper.metadata["hugging_face"] = {
            "url": f"https://huggingface.co/papers/{arxiv_id}",
            "upvotes": paper_data.get("upvotes"),
            "submitted_by": paper_data.get("submittedBy"),
            "summary": paper_data.get("summary"),
        }
        _merge_links(paper, [paper_data.get("githubRepo")], kind="code")
        _merge_links(paper, [paper_data.get("projectPage")], kind="project")

    linked: dict[str, list[str]] = {}
    for repo_type in ("models", "datasets", "spaces"):
        data = _get_json(
            f"https://huggingface.co/api/{repo_type}?filter=arxiv:{arxiv_id}&limit=5"
        )
        if isinstance(data, list):
            linked[repo_type] = [
                item.get("id") or item.get("modelId")
                for item in data
                if isinstance(item, dict) and (item.get("id") or item.get("modelId"))
            ]
    if linked:
        paper.metadata.setdefault("hugging_face", {})["linked_repos"] = linked


def enrich_with_papers_with_code(paper: Paper) -> None:
    arxiv_id = extract_arxiv_id(paper)
    if not arxiv_id:
        return

    data = _get_json(f"https://paperswithcode.com/api/v1/papers/?arxiv_id={arxiv_id}")
    if not isinstance(data, dict):
        return

    results = data.get("results") or []
    if not results:
        return
    pwc_paper = results[0]
    paper.metadata["papers_with_code"] = {
        "url": pwc_paper.get("url_abs") or pwc_paper.get("url_pdf"),
        "tasks": pwc_paper.get("tasks"),
    }

    paper_id = pwc_paper.get("id")
    if paper_id:
        repo_data = _get_json(
            f"https://paperswithcode.com/api/v1/papers/{paper_id}/repositories/"
        )
        if isinstance(repo_data, dict):
            repos = [
                repo.get("url")
                for repo in repo_data.get("results", [])
                if isinstance(repo, dict)
            ]
            _merge_links(paper, repos, kind="code")
            paper.metadata["papers_with_code"]["repositories"] = repos


def check_papers_with_code_exists(arxiv_id: str) -> bool:
    """Check if a paper has Papers with Code entry without full enrichment."""
    if not arxiv_id:
        return False
    try:
        data = _get_json(
            f"https://paperswithcode.com/api/v1/papers/?arxiv_id={arxiv_id}"
        )
        if isinstance(data, dict) and data.get("results"):
            return True
    except Exception:
        pass
    return False


def prefilter_papers_with_code(
    papers: list["Paper"], min_ratio: float = 0.4
) -> list["Paper"]:
    """Ensure at least min_ratio of papers have code implementations.

    This function checks Papers with Code for each paper and prioritizes
    papers with code implementations in the final selection.
    """
    if min_ratio <= 0 or not papers:
        return papers

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from loguru import logger

    logger.info(
        f"Checking Papers with Code availability for {len(papers)} papers (parallel)..."
    )

    arxiv_ids = [extract_arxiv_id(p) or "" for p in papers]
    has_code_map = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_idx = {
            executor.submit(check_papers_with_code_exists, aid): idx
            for idx, aid in enumerate(arxiv_ids)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            has_code_map[idx] = future.result()

    papers_with_code = []
    papers_without_code = []

    for idx, paper in enumerate(papers):
        has_code = has_code_map.get(idx, False)
        paper.metadata["has_code"] = has_code
        if has_code:
            papers_with_code.append(paper)
        else:
            papers_without_code.append(paper)

    logger.info(
        f"Found {len(papers_with_code)} papers with code, {len(papers_without_code)} without"
    )

    min_required = int(len(papers) * min_ratio)
    if len(papers_with_code) >= min_required:
        logger.info(
            f"Papers with code ratio satisfied: {len(papers_with_code)}/{len(papers)} >= {min_ratio:.0%}"
        )
        return papers

    if len(papers_with_code) == 0:
        logger.warning(
            f"No papers with code found. Cannot satisfy {min_ratio:.0%} requirement."
        )
        return papers

    logger.info(
        f"Prioritizing {len(papers_with_code)} papers with code to meet {min_ratio:.0%} requirement"
    )

    result = papers_with_code + papers_without_code
    return result


def enrich_papers(papers: list[Paper], config) -> dict[str, list[str]]:
    if not config.get("enabled", True):
        return {}

    failures: dict[str, list[str]] = {}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
    providers = list(
        config.get(
            "providers", ["semantic_scholar", "hugging_face", "papers_with_code"]
        )
    )

    for paper in papers:
        for provider in providers:
            try:
                if provider == "semantic_scholar":
                    enrich_with_semantic_scholar(paper, api_key)
                elif provider == "hugging_face":
                    enrich_with_hugging_face(paper)
                elif provider == "papers_with_code":
                    enrich_with_papers_with_code(paper)
            except Exception as exc:
                failures.setdefault(provider, []).append(paper.title)
                logger.warning(f"{provider} enrichment failed for {paper.title}: {exc}")
    return failures
