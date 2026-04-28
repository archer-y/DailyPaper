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
        "published_date": paper.published_date.strftime("%Y-%m-%d")
        if paper.published_date
        else None,
    }


def render_markdown(
    papers: list[Paper],
    report_date: str,
    enrichment_failures: dict[str, list[str]] | None = None,
) -> str:
    lines = [
        f"# 📚 论文日报 - {report_date}",
        "",
        f"今日精选 **{len(papers)}** 篇论文，来自多源整合。",
        "",
    ]

    if not papers:
        lines.extend(["今天没有匹配的新论文。", ""])

    source_stats = {}
    for paper in papers:
        src = paper.metadata.get("primary_source", "unknown")
        source_stats[src] = source_stats.get(src, 0) + 1

    if source_stats:
        src_str = " | ".join([f"{k}: {v}篇" for k, v in source_stats.items()])
        lines.extend([f"**来源分布**: {src_str}", ""])

    for index, paper in enumerate(papers, start=1):
        score = f"{paper.score:.2f}" if paper.score is not None else "N/A"
        weighted_score = paper.metadata.get("weighted_score", 0)

        authors = ", ".join(paper.authors[:3]) + (
            " et al." if len(paper.authors) > 3 else ""
        )

        source = paper.metadata.get("primary_source", "unknown")
        source_icon = {
            "arxiv": "📄",
            "openalex": "🔍",
            "huggingface": "🤗",
            "openreview": "🎓",
            "pwc": "💻",
        }.get(source, "📄")

        code_links = paper.code_urls[:2] if paper.code_urls else []
        code_str = (
            " | ".join([f"[代码]({url})" for url in code_links])
            if code_links
            else "暂无"
        )

        hf_upvotes = paper.metadata.get("hf_upvotes", 0)
        github_stars = paper.metadata.get("github_stars", 0)

        social_metrics = []
        if hf_upvotes:
            social_metrics.append(f"👍 {hf_upvotes}")
        if github_stars:
            social_metrics.append(f"⭐ {github_stars}")
        social_str = " | ".join(social_metrics) if social_metrics else ""

        tldr = (
            paper.tldr
            or (paper.metadata.get("semantic_scholar") or {}).get("tldr")
            or ""
        )

        lines.extend(
            [
                f"## {index}. {paper.title}",
                "",
                f"{source_icon} **{source}** | 分数: {score} | 权重分: {weighted_score:.2f}",
                "",
                f"> 💡 **摘要**: {tldr[:150] + '...' if len(tldr) > 150 else tldr}"
                if tldr
                else "> 💡 点击下方链接查看详情",
                "",
                f"👨‍🔬 {authors or 'Unknown'}",
                "",
            ]
        )

        pub_date_str = (
            paper.published_date.strftime("%Y-%m-%d")
            if paper.published_date
            else "未知"
        )
        lines.extend([f"📅 发布日期: {pub_date_str}", ""])

        links = []
        if paper.url:
            links.append(f"[论文]({paper.url})")
        if paper.pdf_url:
            links.append(f"[PDF]({paper.pdf_url})")
        if code_str != "暂无":
            links.append(code_str)

        if links:
            lines.extend([f"🔗 {' | '.join(links)}", ""])

        if social_str:
            lines.extend([f"📊 {social_str}", ""])

        keyword_matches = paper.metadata.get("keyword_matches", 0)
        if keyword_matches:
            lines.extend([f"🏷️ 命中关键词: {keyword_matches}个", ""])

        lines.append("---")
        lines.append("")

    if enrichment_failures:
        lines.extend(["## ⚠️ 元数据补强失败", ""])
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

    records = [
        paper_to_record(paper, rank) for rank, paper in enumerate(papers, start=1)
    ]
    json_path = data_dir / f"{report_date}.json"
    md_path = reports_dir / f"{report_date}.md"

    payload = {
        "date": report_date,
        "paper_count": len(papers),
        "papers": records,
        "enrichment_failures": enrichment_failures or {},
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(
        render_markdown(papers, report_date, enrichment_failures), encoding="utf-8"
    )
    return md_path, json_path
