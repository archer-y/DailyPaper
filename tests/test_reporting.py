import json
from pathlib import Path

from omegaconf import OmegaConf

from tests.canned_responses import make_sample_paper
from zotero_arxiv_daily.reporting import paper_to_record, render_markdown, write_outputs


def test_paper_to_record_includes_enrichment_fields():
    paper = make_sample_paper(
        doi="10.123/example",
        code_urls=["https://github.com/example/repo"],
        project_urls=["https://example.com"],
        metadata={"semantic_scholar": {"citation_count": 3}},
    )
    record = paper_to_record(paper, 1)
    assert record["doi"] == "10.123/example"
    assert record["code_urls"] == ["https://github.com/example/repo"]
    assert record["metadata"]["semantic_scholar"]["citation_count"] == 3


def test_render_markdown_empty_report():
    markdown = render_markdown([], "2026-04-26")
    assert "今天没有匹配的新论文" in markdown


def test_write_outputs_creates_markdown_and_json(monkeypatch):
    written = {}
    made_dirs = []

    def fake_mkdir(self, parents=False, exist_ok=False):
        made_dirs.append((str(self), parents, exist_ok))

    def fake_write_text(self, text, encoding=None):
        written[str(self)] = text
        return len(text)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)
    monkeypatch.setattr(Path, "write_text", fake_write_text)

    config = OmegaConf.create(
        {
            "timezone": "Asia/Shanghai",
            "reports_dir": "reports",
            "data_dir": "data",
        }
    )
    md_path, json_path = write_outputs([make_sample_paper(tldr="一句话总结")], config)

    assert ("reports", True, True) in made_dirs
    assert ("data", True, True) in made_dirs
    assert str(md_path) in written
    assert str(json_path) in written
    payload = json.loads(written[str(json_path)])
    assert payload["paper_count"] == 1
