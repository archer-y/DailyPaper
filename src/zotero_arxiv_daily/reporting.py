from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .enrichment import extract_arxiv_id
from .protocol import Paper


def today_string(timezone: str) -> str:
    return datetime.now(ZoneInfo(timezone)).strftime("%Y-%m-%d")


def paper_to_record(paper: Paper, rank: int) -> dict:
    return {
        "rank": rank,
        "source": paper.source,
        "title": paper.title,
        "authors": paper.authors,
        "abstract": paper.abstract,
        "url": paper.url,
        "pdf_url": paper.pdf_url,
        "arxiv_id": extract_arxiv_id(paper),
        "doi": paper.doi,
        "score": paper.score,
        "tldr": paper.tldr,
        "affiliations": paper.affiliations,
        "code_urls": paper.code_urls,
        "project_urls": paper.project_urls,
        "metadata": paper.metadata,
    }


def render_markdown(papers: list[Paper], report_date: str, enrichment_failures: dict[str, list[str]] | None = None) -> str:
    lines = [
        f"# Zotero 个性化论文日报 - {report_date}",
        "",
        f"今日精选 {len(papers)} 篇论文，按 Zotero 文献库相关性排序。",
        "",
    ]

    if not papers:
        lines.extend(["今天没有匹配的新论文。", ""])
    for index, paper in enumerate(papers, start=1):
        score = f"{paper.score:.2f}" if paper.score is not None else "N/A"
        authors = ", ".join(paper.authors[:5]) + (" et al." if len(paper.authors) > 5 else "")
        code_links = ", ".join(paper.code_urls) if paper.code_urls else "未发现"
        project_links = ", ".join(paper.project_urls) if paper.project_urls else "未发现"
        semantic_tldr = (paper.metadata.get("semantic_scholar") or {}).get("tldr")

        lines.extend(
            [
                f"## {index}. {paper.title}",
                "",
                f"- 相关性分数：{score}",
                f"- 作者：{authors or 'Unknown'}",
                f"- 论文：{paper.url}",
                f"- PDF：{paper.pdf_url or '未发现'}",
                f"- 代码：{code_links}",
                f"- 项目页：{project_links}",
                f"- 一句话结论：{paper.tldr or semantic_tldr or '暂无'}",
                f"- 研究问题：{paper.abstract[:280].strip()}",
                "- 核心方法：见摘要与 TLDR；第一版不额外编造未抽取到的方法细节。",
                "- 主要贡献：由 TLDR 与摘要辅助判断，优先阅读原文确认。",
                "- 局限：自动摘要未可靠覆盖局限性，建议阅读实验和讨论部分。",
                f"- 推荐理由：与你的 Zotero 文献库相似度较高，且命中领域关键词 {paper.metadata.get('keyword_matches', 0)} 个。",
                "",
            ]
        )

    if enrichment_failures:
        lines.extend(["## 元数据补强失败", ""])
        for provider, titles in enrichment_failures.items():
            lines.append(f"- {provider}: {len(titles)} 篇失败")
        lines.append("")

    return "\n".join(lines)


def write_outputs(
    papers: list[Paper],
    config,
    enrichment_failures: dict[str, list[str]] | None = None,
) -> tuple[Path, Path]:
    report_date = today_string(config.timezone)
    reports_dir = Path(config.reports_dir)
    data_dir = Path(config.data_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    records = [paper_to_record(paper, rank) for rank, paper in enumerate(papers, start=1)]
    json_path = data_dir / f"{report_date}.json"
    md_path = reports_dir / f"{report_date}.md"

    payload = {
        "date": report_date,
        "paper_count": len(papers),
        "papers": records,
        "enrichment_failures": enrichment_failures or {},
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(papers, report_date, enrichment_failures), encoding="utf-8")
    return md_path, json_path
