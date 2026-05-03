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


def pluralize(count: Any, singular: str, plural: str | None = None) -> str:
    value = int(count or 0)
    noun = singular if value == 1 else (plural or f"{singular}s")
    return f"{value} {noun}"


def compact_date(text: str) -> str:
    value = first_present(text)
    if not value:
        return ""
    return value.split("T", 1)[0].split(" ", 1)[0]


def index_papers(record: dict[str, Any]) -> list[dict[str, Any]]:
    papers = record.get("papers")
    if isinstance(papers, list) and papers:
        return [paper for paper in papers if isinstance(paper, dict)]

    fallback: list[dict[str, Any]] = []
    for year in record.get("years") or []:
        for paper in (year or {}).get("data_related_papers") or []:
            if isinstance(paper, dict):
                fallback.append(paper)
    return fallback


def paper_meta_text(paper: dict[str, Any]) -> str:
    parts: list[str] = []
    month = first_present(paper.get("month"))
    published_at = compact_date(first_present(paper.get("published_at")))
    if month:
        parts.append(month)
    if published_at and published_at != month:
        parts.append(published_at)
    if paper.get("has_observational_catalog") is True:
        parts.append("data-related")
    return "; ".join(parts)


def render_month_note(record: dict[str, Any]) -> str:
    config = record.get("config") or {}
    stats = record.get("stats") or {}
    run = record.get("run") or {}
    papers = record.get("papers") or []
    month = str(record.get("month") or "")
    source = str(config.get("source") or "")

    lines: list[str] = []
    lines.append(f"# High-Velocity Star Literature Note - {month}")
    lines.append("")
    lines.append(f"- Date range: {record.get('date_from')} to {record.get('date_to')}")
    lines.append(f"- Run ID: `{run.get('run_id')}`")
    lines.append(f"- Started at: {run.get('started_at')}")
    source_label = "DeepXiv SDK" if source == "deepxiv" else "arXiv API"
    lines.append(f"- Candidate search: {source_label}; up to `{config.get('max_results')}` records per query")
    if source == "deepxiv":
        lines.append(f"- DeepXiv search mode: `{config.get('search_mode')}`")
    categories = config.get("categories") or []
    if categories:
        lines.append(f"- Category filter: {', '.join(f'`{cat}`' for cat in categories)}")
    if config.get("min_score") is not None:
        lines.append(f"- DeepXiv score floor: `{config.get('min_score')}`")
    if config.get("llm_review"):
        lines.append(
            f"- Title triage: rules first; titles without clear evidence reviewed by LLM `{config.get('llm_model')}`"
        )
    else:
        lines.append("- Title triage: rules only")
    lines.append(
        f"- Deduplicated candidates: {pluralize(stats.get('raw_unique', 0), 'paper')}; "
        f"final included literature: {pluralize(stats.get('relevant_count', 0), 'paper')}"
    )
    lines.append(
        f"- Title triage counts: rule-related {pluralize(stats.get('rule_related_count', 0), 'paper')}; "
        f"no clear title evidence {pluralize(stats.get('no_clear_title_evidence_count', 0), 'paper')}; "
        f"LLM reviewed {pluralize(stats.get('llm_reviewed_count', 0), 'paper')}; "
        f"LLM confirmed {pluralize(stats.get('llm_confirmed_count', 0), 'paper')}; "
        f"LLM skipped {pluralize(stats.get('llm_skipped_count', 0), 'paper')}"
    )
    lines.append(
        f"- Filtering stats: date-window-filtered {pluralize(stats.get('date_window_filtered', 0), 'paper')}; "
        f"missing publication date {pluralize(stats.get('missing_publication_date', 0), 'paper')}; "
        f"category-filtered {pluralize(stats.get('category_filtered', 0), 'paper')}; "
        f"score-filtered {pluralize(stats.get('score_filtered', 0), 'paper')}"
    )
    if int(stats.get("deepxiv_fallback_count") or 0) > 0:
        lines.append(
            f"- DeepXiv fallback: switched to arXiv for {pluralize(stats.get('deepxiv_fallback_count', 0), 'query')}"
        )
    if int(stats.get("arxiv_metadata_requested_count") or 0) > 0:
        lines.append(
            f"- arXiv metadata backfill: attempted {pluralize(stats.get('arxiv_metadata_requested_count', 0), 'paper')} missing dates; "
            f"publication date rescued {pluralize(stats.get('arxiv_publication_date_backfilled_count', 0), 'paper')}; "
            f"timed out {pluralize(stats.get('arxiv_metadata_timeout_count', 0), 'paper')}; "
            f"other errors {pluralize(stats.get('arxiv_metadata_error_count', 0), 'paper')}; "
            f"fetched but publication date still missing {pluralize(stats.get('arxiv_metadata_no_publication_date_count', 0), 'paper')}"
        )
    catalog_summary = record.get("catalog_assessment_summary") or {}
    if catalog_summary:
        lines.append(
            f"- Observational catalog assessment: assessed {pluralize(catalog_summary.get('assessed_count', 0), 'paper')}; "
            f"likely observational catalog/sample {pluralize(catalog_summary.get('catalog_count', 0), 'paper')}; "
            f"method `{catalog_summary.get('method')}` / `{catalog_summary.get('model')}`"
        )
    lines.append("")
    lines.append("## Search Queries")
    lines.append("")
    for query in config.get("queries") or []:
        lines.append(f"- `{query}`")
    lines.append("")
    lines.append("## Monthly Results")
    lines.append("")

    if not papers:
        lines.append("No DeepXiv/arXiv results were included in this month's note.")
        lines.append("")
    else:
        lines.append("Sorted by publication date and score.")
        lines.append("")
        for item_index, paper in enumerate(papers, start=1):
            links = paper.get("links") or {}
            abstract = paper.get("abstract") or {}
            match = paper.get("match") or {}
            deepxiv = paper.get("deepxiv") or {}
            catalog_assessment = paper.get("catalog_assessment") or {}
            arxiv_id = first_present(paper.get("arxiv_id"))
            title = first_present(paper.get("title"), "Untitled")
            abstract_text = first_present(abstract.get("text"))
            keywords = first_present(deepxiv.get("search_keywords"))
            publish_at = first_present(paper.get("published_at"))
            authors = first_present(paper.get("author_names"), paper.get("authors"))
            categories_text = first_present(paper.get("categories"))
            citations = first_present(deepxiv.get("citations"))
            score = first_present(match.get("best_score"), deepxiv.get("best_score"), deepxiv.get("score"))
            matched_queries = ", ".join(f"`{q}`" for q in match.get("queries", []))
            matched_categories = ", ".join(f"`{cat}`" for cat in match.get("categories", []))

            lines.append(f"### {item_index}. {title}")
            lines.append("")
            abs_url = first_present(links.get("abs"))
            pdf = first_present(links.get("pdf"))
            if arxiv_id and abs_url and pdf:
                lines.append(f"- arXiv: [{arxiv_id}]({abs_url}); [PDF]({pdf})")
            elif arxiv_id:
                lines.append(f"- arXiv: {arxiv_id}")
            if publish_at:
                lines.append(f"- Published at: {publish_at}")
            if authors:
                lines.append(f"- Authors: {authors}")
            if categories_text:
                lines.append(f"- Categories: {categories_text}")
            if citations:
                lines.append(f"- Citations: {citations}")
            if score:
                lines.append(f"- DeepXiv score: {score}")
            if matched_queries:
                lines.append(f"- Matched queries: {matched_queries}")
            if matched_categories:
                lines.append(f"- Matched categories: {matched_categories}")
            if catalog_assessment:
                has_catalog = "Likely" if catalog_assessment.get("has_observational_catalog") else "Unlikely"
                data_products = first_present(catalog_assessment.get("data_products"))
                lines.append(
                    f"- Observational catalog assessment: {has_catalog}; "
                    f"role={catalog_assessment.get('catalog_role')}; "
                    f"scope={catalog_assessment.get('object_scope')}; "
                    f"confidence={catalog_assessment.get('confidence')}; "
                    f"{catalog_assessment.get('evidence') or ''}"
                )
                if data_products:
                    lines.append(f"- Possible data products: {data_products}")
            if keywords:
                lines.append(f"- DeepXiv keywords: {keywords}")
            if abstract_text:
                lines.append("")
                lines.append("**Search Abstract**")
                lines.append("")
                lines.append(abstract_text)
            lines.append("")

    lines.append("## Monthly Run Log Summary")
    lines.append("")
    lines.append("| Query | Source | Category | Total | Returned | Error |")
    lines.append("| --- | --- | --- | ---: | ---: | --- |")
    for row in record.get("search_log") or []:
        query = escape_pipe(str(row.get("query") or ""))
        row_source = escape_pipe(str(row.get("source") or source))
        category = escape_pipe(str(row.get("category") or ""))
        total = row.get("total", "")
        returned = row.get("returned", "")
        error = escape_pipe(str(row.get("error") or ""))
        lines.append(f"| `{query}` | `{row_source}` | `{category}` | {total} | {returned} | {error} |")
    lines.append("")
    return "\n".join(lines)


def render_index(record: dict[str, Any]) -> str:
    if record.get("years") is None:
        run = record.get("run") or {}
        lines = [
            "# Monthly High-Velocity Star Literature Index",
            "",
            f"- Run ID: `{run.get('run_id')}`",
            f"- Started at: {run.get('started_at')}",
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

    summary = record.get("summary") or {}
    years = record.get("years") or []
    papers = index_papers(record)
    recent_papers = papers[:12]
    first_year = first_present((years[-1] or {}).get("year")) if years else ""
    last_year = first_present((years[0] or {}).get("year")) if years else ""

    lines = [
        "# Yearly High-Velocity Star Literature Index",
        "",
        f"- Generated at: {record.get('generated_at')}",
    ]
    if first_year and last_year:
        lines.append(f"- Coverage: {first_year} to {last_year}")
    if papers:
        lines.append(f"- Indexed papers available for sampling: {pluralize(len(papers), 'paper')}")
    lines.append(f"- Total relevant literature: {pluralize(summary.get('literature_count', 0), 'paper')}")
    lines.append(f"- Total data-related literature: {pluralize(summary.get('data_related_count', 0), 'paper')}")

    if recent_papers:
        lines.extend(["", "## Recent Literature", ""])
        for paper in recent_papers:
            title = first_present(paper.get("title"), "Untitled")
            navigation_path = first_present(paper.get("navigation_path"))
            meta = paper_meta_text(paper)
            line = f"- [{title}]({navigation_path})" if navigation_path else f"- {title}"
            if meta:
                line += f" - {meta}"
            lines.append(line)

    lines.extend(
        [
            "",
            "## Year Overview",
            "",
            "| Year | Relevant literature | Data-related literature |",
            "| --- | ---: | ---: |",
        ]
    )
    for year in years:
        lines.append(
            f"| {year.get('year')} | {year.get('literature_count', 0)} | {year.get('data_related_count', 0)} |"
        )

    for year in years:
        year_papers = year.get("data_related_papers") or []
        if not year_papers:
            continue
        lines.append("")
        lines.append(f"## {year.get('year')}")
        lines.append("")
        lines.append(f"Data-related literature: {pluralize(year.get('data_related_count', 0), 'paper')}")
        lines.append("")
        for paper in year_papers:
            title = first_present(paper.get("title"), "Untitled")
            navigation_path = first_present(paper.get("navigation_path"))
            meta = paper_meta_text(paper)
            line = f"- [{title}]({navigation_path})" if navigation_path else f"- {title}"
            if meta:
                line += f" - {meta}"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)
