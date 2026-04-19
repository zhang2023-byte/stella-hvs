"""Markdown rendering helpers for canonical literature JSON records."""

from __future__ import annotations

from typing import Any


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


def is_weak_match(paper: dict[str, Any]) -> bool:
    triage = paper.get("triage") or {}
    return triage.get("level") == "weak"


def render_month_note(record: dict[str, Any]) -> str:
    config = record.get("config") or {}
    stats = record.get("stats") or {}
    run = record.get("run") or {}
    papers = record.get("papers") or []
    month = str(record.get("month") or "")
    source = str(config.get("source") or "")

    lines: list[str] = []
    lines.append(f"# 高速星文献简介 - {month}")
    lines.append("")
    lines.append(f"- 日期范围：{record.get('date_from')} 至 {record.get('date_to')}")
    lines.append(f"- 运行编号：`{run.get('run_id')}`")
    lines.append(f"- 运行时间：{run.get('started_at')}")
    source_label = "DeepXiv SDK" if source == "deepxiv" else "arXiv API"
    lines.append(f"- 候选检索：{source_label}；每个关键词最多取 `{config.get('max_results')}` 条")
    if source == "deepxiv":
        lines.append(f"- DeepXiv 搜索模式：`{config.get('search_mode')}`")
    categories = config.get("categories") or []
    if categories:
        lines.append(f"- 分类过滤：{', '.join(f'`{cat}`' for cat in categories)}")
    if config.get("min_score") is not None:
        lines.append(f"- DeepXiv score 下限：`{config.get('min_score')}`")
    if config.get("classifier") == "llm":
        lines.append(f"- 标题复核：LLM `{config.get('llm_model')}`，base URL `{config.get('llm_base_url')}`")
    elif config.get("classifier") == "rules" and config.get("llm_review"):
        lines.append(f"- 标题复核：直接相关规则自动收录；弱相关规则交给 LLM `{config.get('llm_model')}` 复核")
    else:
        lines.append(f"- 标题复核：`{config.get('classifier')}`")
    if config.get("use_brief"):
        lines.append(
            f"- 简介生成：DeepXiv `brief` 仅用于强相关/直接相关；"
            f"本月拉取 {stats.get('brief_eligible_count', 0)} 篇，"
            f"弱相关跳过 {stats.get('brief_skipped_weak_count', 0)} 篇"
        )
    else:
        lines.append("- 简介生成：DeepXiv `brief` 未启用")
    lines.append(f"- 去重后候选：{stats.get('raw_unique', 0)} 篇；标题复核通过：{stats.get('relevant_count', 0)} 篇")
    lines.append(
        f"- 清洗统计：分类过滤 {stats.get('category_filtered', 0)} 篇；"
        f"score 过滤 {stats.get('score_filtered', 0)} 篇；"
        f"标题复核过滤 {stats.get('classifier_filtered', 0)} 篇"
    )
    if config.get("classifier") == "rules":
        rule_summary = (
            f"- 规则分层：直接相关 {stats.get('direct_rule_included', 0)} 篇；"
            f"弱相关 {stats.get('weak_rule_candidates', 0)} 篇"
        )
        if config.get("llm_review"):
            rule_summary += (
                f"；弱相关 LLM 复核 {stats.get('weak_llm_reviewed', 0)} 篇；"
                f"复核后保留 {stats.get('weak_llm_included', 0)} 篇"
            )
        lines.append(rule_summary)
    catalog_summary = record.get("catalog_assessment_summary") or {}
    if catalog_summary:
        lines.append(
            f"- 观测 catalog 判定：已判定 {catalog_summary.get('assessed_count', 0)} 篇；"
            f"疑似包含真实观测 catalog/样本 {catalog_summary.get('catalog_count', 0)} 篇；"
            f"方法 `{catalog_summary.get('method')}` / `{catalog_summary.get('model')}`"
        )
    lines.append("")
    lines.append("## 检索关键词")
    lines.append("")
    for query in config.get("queries") or []:
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
                links = paper.get("links") or {}
                brief = paper.get("brief") or {}
                abstract = paper.get("abstract") or {}
                match = paper.get("match") or {}
                triage = paper.get("triage") or {}
                deepxiv = paper.get("deepxiv") or {}
                catalog_assessment = paper.get("catalog_assessment") or {}

                arxiv_id = first_present(paper.get("arxiv_id"))
                title = first_present(paper.get("title"), "Untitled")
                tldr = first_present(brief.get("tldr"))
                abstract_text = first_present(abstract.get("text"))
                keywords = first_present(brief.get("keywords"), deepxiv.get("search_keywords"))
                publish_at = first_present(paper.get("published_at"), brief.get("published_at"))
                authors = first_present(paper.get("author_names"), paper.get("authors"))
                categories_text = first_present(paper.get("categories"))
                citations = first_present(brief.get("citations"), deepxiv.get("citations"))
                score = first_present(match.get("best_score"), deepxiv.get("best_score"), deepxiv.get("score"))
                matched_queries = ", ".join(f"`{q}`" for q in match.get("queries", []))
                matched_categories = ", ".join(f"`{cat}`" for cat in match.get("categories", []))

                lines.append(f"### {item_index}. {title}")
                lines.append("")
                abs_url = first_present(links.get("abs"))
                pdf = first_present(links.get("pdf"))
                if arxiv_id and abs_url and pdf:
                    lines.append(f"- arXiv：[{arxiv_id}]({abs_url})；[PDF]({pdf})")
                elif arxiv_id:
                    lines.append(f"- arXiv：{arxiv_id}")
                if publish_at:
                    lines.append(f"- 发布时间：{publish_at}")
                if authors:
                    lines.append(f"- 作者：{authors}")
                if categories_text:
                    lines.append(f"- 分类：{categories_text}")
                if citations:
                    lines.append(f"- 引用数：{citations}")
                if score:
                    lines.append(f"- DeepXiv score：{score}")
                if matched_queries:
                    lines.append(f"- 命中关键词：{matched_queries}")
                if matched_categories:
                    lines.append(f"- 命中分类：{matched_categories}")
                if triage:
                    lines.append(
                        f"- 标题复核：{triage.get('label')}，"
                        f"confidence={triage.get('confidence')}，{triage.get('reason') or ''}"
                    )
                if catalog_assessment:
                    has_catalog = "是" if catalog_assessment.get("has_observational_catalog") else "否"
                    data_products = first_present(catalog_assessment.get("data_products"))
                    lines.append(
                        f"- 观测 catalog 判定：{has_catalog}；"
                        f"role={catalog_assessment.get('catalog_role')}；"
                        f"scope={catalog_assessment.get('object_scope')}；"
                        f"confidence={catalog_assessment.get('confidence')}；"
                        f"{catalog_assessment.get('evidence') or ''}"
                    )
                    if data_products:
                        lines.append(f"- 可能数据产品：{data_products}")
                if not brief.get("fetched") and brief.get("skipped_reason"):
                    lines.append("- DeepXiv brief：弱相关条目未拉取；仅保留 search 阶段元数据")
                if keywords:
                    lines.append(f"- DeepXiv keywords：{keywords}")
                if tldr:
                    lines.append("")
                    lines.append("**DeepXiv brief**")
                    lines.append("")
                    lines.append(tldr)
                if abstract_text:
                    lines.append("")
                    lines.append("**Search 返回摘要**")
                    lines.append("")
                    lines.append(abstract_text)
                lines.append("")

    lines.append("## 本月运行日志摘要")
    lines.append("")
    total_label = "DeepXiv total" if source == "deepxiv" else "arXiv total"
    lines.append(f"| Query | Category | {total_label} | Returned | Error |")
    lines.append("| --- | --- | ---: | ---: | --- |")
    for row in record.get("search_log") or []:
        query = escape_pipe(str(row.get("query") or ""))
        category = escape_pipe(str(row.get("category") or ""))
        total = row.get("total", "")
        returned = row.get("returned", "")
        error = escape_pipe(str(row.get("error") or ""))
        lines.append(f"| `{query}` | `{category}` | {total} | {returned} | {error} |")
    lines.append("")
    return "\n".join(lines)


def render_index(record: dict[str, Any]) -> str:
    run = record.get("run") or {}
    lines = [
        "# 高速星逐月文献索引",
        "",
        f"- 运行编号：`{run.get('run_id')}`",
        f"- 运行时间：{run.get('started_at')}",
        "",
        "| Month | Relevant papers | Unique candidates | Note |",
        "| --- | ---: | ---: | --- |",
    ]
    for summary in record.get("months") or []:
        slug = summary["month"]
        lines.append(
            f"| {slug} | {summary['relevant_count']} | {summary['raw_unique']} | "
            f"[{slug}.md]({slug}/{slug}.md) |"
        )
    lines.append("")
    return "\n".join(lines)
