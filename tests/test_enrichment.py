from zotero_arxiv_daily.enrichment import (
    apply_keyword_boost,
    deduplicate_papers,
    extract_arxiv_id,
)
from tests.canned_responses import make_sample_paper


def test_extract_arxiv_id_from_abs_url():
    paper = make_sample_paper(url="https://arxiv.org/abs/2601.12345v2")
    assert extract_arxiv_id(paper) == "2601.12345"


def test_deduplicate_papers_by_arxiv_id():
    papers = [
        make_sample_paper(title="Paper A", url="https://arxiv.org/abs/2601.00001"),
        make_sample_paper(title="Paper B", url="https://arxiv.org/abs/2601.00001v2"),
    ]
    assert [p.title for p in deduplicate_papers(papers)] == ["Paper A"]


def test_deduplicate_papers_by_near_duplicate_title():
    papers = [
        make_sample_paper(title="A Strong Agentic RAG System for Scientific Discovery", url="https://arxiv.org/abs/2601.00001"),
        make_sample_paper(title="A strong agentic RAG system for scientific discovery!", url="https://example.com/paper"),
    ]
    assert len(deduplicate_papers(papers)) == 1


def test_keyword_boost_resorts_papers():
    low = make_sample_paper(title="Agentic RAG for LLMs", abstract="", score=1.0)
    high = make_sample_paper(title="Other topic", abstract="", score=1.1)
    boosted = apply_keyword_boost([high, low], ["RAG", "LLM"], 0.2)
    assert boosted[0].title == "Agentic RAG for LLMs"
    assert boosted[0].metadata["keyword_matches"] == 2
