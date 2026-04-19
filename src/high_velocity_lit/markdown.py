"""Markdown rendering helpers for monthly literature notes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import MonthWindow, SearchConfig


def escape_pipe(text: str) -> str:
    return text.replace("|", "\\|")


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(as_text(item) for item in value if item)
    return str(value)


def first_present(*values: Any) -> str:
    for value in values:
        text = as_text(value).strip()
        if text:
            return text
    return ""


def classifier_label(paper: dict[str, Any]) -> str:
    classifier = paper.get("_classifier") or {}
    return str(classifier.get("label") or "")


def is_weak_match(paper: dict[str, Any]) -> bool:
    return classifier_label(paper).startswith("rule-weak")


def paper_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/abs/{arxiv_id}"


def pdf_url(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id}"


def render_month_note(
    month: MonthWindow,
    papers: list[dict[str, Any]],
    stats: dict[str, Any],
    config: SearchConfig,
    *,
    run_id: str,
    started_at: datetime,
) -> str:
    lines: list[str] = []
    lines.append(f"# 高速星文献简介 - {month.slug}")
    lines.append("")
    lines.append(f"- 日期范围：{month.date_from} 至 {month.date_to}")
    lines.append(f"- 运行编号：`{run_id}`")
    lines.append(f"- 运行时间：{started_at.isoformat(timespec='seconds')}")
    source_label = "DeepXiv SDK" if config.source == "deepxiv" else "arXiv API"
    lines.append(f"- 候选检索：{source_label}；每个关键词最多取 `{config.max_results}` 条")
    if config.source == "deepxiv":
        lines.append(f"- DeepXiv 搜索模式：`{config.search_mode}`")
    if config.categories:
        lines.append(f"- 分类过滤：{', '.join(f'`{cat}`' for cat in config.categories)}")
    if config.min_score is not None:
        lines.append(f"- DeepXiv score 下限：`{config.min_score}`")
    if config.classifier == "llm":
        lines.append(f"- 标题复核：LLM `{config.llm_model}`，base URL `{config.llm_base_url}`")
    elif config.classifier == "rules" and config.llm_review:
        lines.append(f"- 标题复核：直接相关规则自动收录；弱相关规则交给 LLM `{config.llm_model}` 复核")
    else:
        lines.append(f"- 标题复核：`{config.classifier}`")
    if config.use_brief:
        lines.append(
            f"- 简介生成：DeepXiv `brief` 仅用于强相关/直接相关；"
            f"本月拉取 {stats.get('brief_eligible_count', 0)} 篇，"
            f"弱相关跳过 {stats.get('brief_skipped_weak_count', 0)} 篇"
        )
    else:
        lines.append("- 简介生成：DeepXiv `brief` 未启用")
    lines.append(f"- 去重后候选：{stats['raw_unique']} 篇；标题复核通过：{stats['relevant_count']} 篇")
    lines.append(
        f"- 清洗统计：分类过滤 {stats.get('category_filtered', 0)} 篇；"
        f"score 过滤 {stats.get('score_filtered', 0)} 篇；"
        f"标题复核过滤 {stats.get('classifier_filtered', 0)} 篇"
    )
    if config.classifier == "rules":
        rule_summary = (
            f"- 规则分层：直接相关 {stats.get('direct_rule_included', 0)} 篇；"
            f"弱相关 {stats.get('weak_rule_candidates', 0)} 篇"
        )
        if config.llm_review:
            rule_summary += (
                f"；弱相关 LLM 复核 {stats.get('weak_llm_reviewed', 0)} 篇；"
                f"复核后保留 {stats.get('weak_llm_included', 0)} 篇"
            )
        lines.append(rule_summary)
    lines.append("")
    lines.append("## 检索关键词")
    lines.append("")
    for query in config.queries:
        lines.append(f"- `{query}`")
    lines.append("")
    lines.append("## 本月结果")
    lines.append("")

    if not papers:
        lines.append("本月没有通过标题复核的 DeepXiv/arXiv 结果。")
        lines.append("")
    else:
        lines.append("排序：强相关/直接相关在前，弱相关在后；同一层级内按发布时间和 score 排序。")
        lines.append("")
        grouped_papers = [
            ("强相关 / 直接相关", [paper for paper in papers if not is_weak_match(paper)]),
            ("弱相关", [paper for paper in papers if is_weak_match(paper)]),
        ]
        item_index = 0
        rendered_groups = 0
        for group_title, group_papers in grouped_papers:
            if not group_papers:
                continue
            if rendered_groups:
                lines.append("---")
                lines.append("")
            lines.append(f"**{group_title}**")
            lines.append("")
            rendered_groups += 1
            for paper in group_papers:
                item_index += 1
                idx = item_index
                arxiv_id = first_present(paper.get("arxiv_id"), paper.get("id"))
                title = first_present(paper.get("title"), "Untitled")
                brief = paper.get("_brief") or {}
                tldr = first_present(brief.get("tldr"), paper.get("tldr"))
                abstract = first_present(paper.get("abstract"))
                keywords = first_present(brief.get("keywords"), paper.get("keywords"))
                publish_at = first_present(brief.get("publish_at"), paper.get("publish_at"))
                authors = first_present(paper.get("author_names"), paper.get("authors"))
                categories = first_present(paper.get("categories"))
                citations = first_present(brief.get("citations"), paper.get("citation"))
                score = first_present(paper.get("_best_score"), paper.get("score"))
                matched_queries = ", ".join(f"`{q}`" for q in paper.get("_matched_queries", []))
                matched_categories = ", ".join(f"`{cat}`" for cat in paper.get("_matched_categories", []))
                classifier = paper.get("_classifier") or {}

                lines.append(f"### {idx}. {title}")
                lines.append("")
                lines.append(f"- arXiv：[{arxiv_id}]({paper_url(arxiv_id)})；[PDF]({pdf_url(arxiv_id)})")
                if publish_at:
                    lines.append(f"- 发布时间：{publish_at}")
                if authors:
                    lines.append(f"- 作者：{authors}")
                if categories:
                    lines.append(f"- 分类：{categories}")
                if citations:
                    lines.append(f"- 引用数：{citations}")
                if score:
                    lines.append(f"- DeepXiv score：{score}")
                if matched_queries:
                    lines.append(f"- 命中关键词：{matched_queries}")
                if matched_categories:
                    lines.append(f"- 命中分类：{matched_categories}")
                if classifier:
                    confidence = classifier.get("confidence")
                    label = classifier.get("label") or config.classifier
                    reason = classifier.get("reason") or ""
                    lines.append(f"- 标题复核：{label}，confidence={confidence}，{reason}")
                if paper.get("_brief_skipped"):
                    lines.append("- DeepXiv brief：弱相关条目未拉取；仅保留 search 阶段元数据")
                if keywords:
                    lines.append(f"- DeepXiv keywords：{keywords}")
                if tldr:
                    lines.append("")
                    lines.append("**DeepXiv brief**")
                    lines.append("")
                    lines.append(tldr)
                if abstract:
                    lines.append("")
                    lines.append("**Search 返回摘要**")
                    lines.append("")
                    lines.append(abstract)
                lines.append("")

    lines.append("## 本月运行日志摘要")
    lines.append("")
    total_label = "DeepXiv total" if config.source == "deepxiv" else "arXiv total"
    lines.append(f"| Query | Category | {total_label} | Returned | Error |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for row in stats["query_stats"]:
        query = escape_pipe(row["query"])
        category = escape_pipe(row.get("category") or "")
        total = row.get("total", "")
        returned = row.get("returned", "")
        error = escape_pipe(row.get("error") or "")
        lines.append(f"| `{query}` | `{category}` | {total} | {returned} | {error} |")
    lines.append("")
    return "\n".join(lines)


def render_index(month_summaries: list[dict[str, Any]], *, run_id: str, started_at: datetime) -> str:
    lines = [
        "# 高速星逐月文献索引",
        "",
        f"- 运行编号：`{run_id}`",
        f"- 运行时间：{started_at.isoformat(timespec='seconds')}",
        "",
        "| Month | Relevant papers | Unique candidates | Note |",
        "| --- | ---: | ---: | --- |",
    ]
    for summary in month_summaries:
        slug = summary["month"]
        lines.append(
            f"| {slug} | {summary['relevant_count']} | {summary['raw_unique']} | "
            f"[{slug}.md]({slug}.md) |"
        )
    lines.append("")
    return "\n".join(lines)
