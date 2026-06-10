#!/usr/bin/env python3
"""Score benchmark variants against the gold standard and write reports."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.catalog_review import read_json, relative_path, write_json  # noqa: E402
from stella_benchmark.metrics import (  # noqa: E402
    LOOSE_REL_TOL,
    STRICT_REL_TOL,
    bootstrap_micro_ci,
    detection_summary,
    field_summary,
    paper_status_summary,
    score_paper,
)
from stella_benchmark.models import (  # noqa: E402
    BENCHMARK_REPORT_SCHEMA_VERSION,
    BenchmarkManifest,
    BenchmarkReport,
)
from stella_benchmark.paths import (  # noqa: E402
    benchmark_root,
    gold_candidates_path,
    gold_dir,
    manifest_path,
    report_json_path,
    report_markdown_path,
    variant_candidates_path,
    variants_dir,
)


def registered_variant_ids(root: Path) -> list[str]:
    base = variants_dir(root)
    if not base.exists():
        return []
    return sorted(path.parent.name for path in base.glob("*/variant_meta.json") if path.is_file())


def adjudication_stats(root: Path, paper_ids: list[str]) -> dict[str, object]:
    from stella_benchmark.paths import adjudication_path, gold_provenance_path

    verdict_counts: dict[str, int] = {}
    provenance_counts = {"verdict": 0, "auto_consensus": 0}
    for arxiv_id in paper_ids:
        adjudication_file = adjudication_path(root, arxiv_id)
        if adjudication_file.exists():
            payload = read_json(adjudication_file)
            for item in payload.get("items") or []:
                verdict = str(item.get("verdict") or "")
                verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        provenance_file = gold_provenance_path(root, arxiv_id)
        if provenance_file.exists():
            payload = read_json(provenance_file)
            for entry in payload.get("entries") or []:
                source = str(entry.get("source") or "")
                if source in provenance_counts:
                    provenance_counts[source] += 1
    return {"verdict_counts": verdict_counts, "provenance_counts": provenance_counts}


def render_markdown(report: BenchmarkReport) -> str:
    lines = [
        "# HVS Extraction Benchmark Report",
        "",
        f"- Generated at: {report.generated_at}",
        f"- Gold papers: {len(report.paper_ids)}",
        f"- Variants: {', '.join(report.variant_ids)}",
        f"- Numeric tolerances: strict rel={report.tolerances['strict_rel_tol']}, "
        f"loose rel={report.tolerances['loose_rel_tol']}",
        "",
        "## Candidate Detection",
        "",
        "| Variant | TP | FP | FN | micro P | micro R | micro F1 | macro F1 | no-cand. specificity |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def fmt(value: object) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    for variant_id in report.variant_ids:
        detection = report.detection[variant_id]
        lines.append(
            f"| {variant_id} | {detection['tp']} | {detection['fp']} | {detection['fn']} | "
            f"{fmt(detection['micro_precision'])} | {fmt(detection['micro_recall'])} | "
            f"{fmt(detection['micro_f1'])} | {fmt(detection['macro_f1'])} | "
            f"{fmt(detection['no_candidate_specificity'])} |"
        )
        ci = detection.get("bootstrap_ci") or {}
        if ci:
            lines.append(
                f"  - {variant_id} 95% CI: P {fmt(ci['micro_precision'][0])}-{fmt(ci['micro_precision'][1])}, "
                f"R {fmt(ci['micro_recall'][0])}-{fmt(ci['micro_recall'][1])}, "
                f"F1 {fmt(ci['micro_f1'][0])}-{fmt(ci['micro_f1'][1])}"
            )

    lines.extend(["", "## Paper Status", ""])
    for variant_id in report.variant_ids:
        status = report.paper_status[variant_id]
        lines.append(f"- {variant_id}: accuracy {fmt(status['accuracy'])}")

    lines.extend(["", "## Field Accuracy (headline fields, gold-present cells)", ""])
    lines.append("| Variant | strict accuracy | loose accuracy |")
    lines.append("| --- | ---: | ---: |")
    for variant_id in report.variant_ids:
        headline = report.fields[variant_id]["headline"]
        lines.append(
            f"| {variant_id} | {fmt(headline['strict']['accuracy'])} | "
            f"{fmt(headline['loose']['accuracy'])} |"
        )

    stats = report.adjudication_stats
    if stats:
        lines.extend(["", "## Adjudication Provenance", ""])
        verdicts = stats.get("verdict_counts") or {}
        for verdict in sorted(verdicts):
            lines.append(f"- verdict {verdict}: {verdicts[verdict]}")
        provenance = stats.get("provenance_counts") or {}
        lines.append(
            f"- gold items from explicit verdicts: {provenance.get('verdict', 0)}, "
            f"auto-consensus: {provenance.get('auto_consensus', 0)}"
        )
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score variants against benchmark gold.")
    parser.add_argument("--benchmark-root", type=Path, default=benchmark_root(WORKSPACE))
    parser.add_argument("--variants", nargs="*", help="Variant ids (default: all registered).")
    parser.add_argument("--strict-rel-tol", type=float, default=STRICT_REL_TOL)
    parser.add_argument("--loose-rel-tol", type=float, default=LOOSE_REL_TOL)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260610)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.benchmark_root.expanduser()
    manifest_file = manifest_path(root)
    if not manifest_file.exists():
        raise SystemExit(f"benchmark manifest does not exist: {manifest_file}")
    manifest = BenchmarkManifest.model_validate(read_json(manifest_file))

    variant_ids = args.variants or registered_variant_ids(root)
    if not variant_ids:
        raise SystemExit("no registered variants found")

    gold_papers: dict[str, dict[str, object]] = {}
    skipped: list[str] = []
    for paper in manifest.papers:
        path = gold_candidates_path(root, paper.arxiv_id)
        if path.exists():
            gold_papers[paper.arxiv_id] = read_json(path)
        else:
            skipped.append(paper.arxiv_id)
            print(f"skipping {paper.arxiv_id}: no gold record", file=sys.stderr)
    if not gold_papers:
        raise SystemExit(f"no gold records found under {gold_dir(root)}")

    detection: dict[str, object] = {}
    paper_status: dict[str, object] = {}
    fields: dict[str, object] = {}
    for variant_id in variant_ids:
        paper_scores: dict[str, dict[str, object]] = {}
        for arxiv_id, gold_payload in gold_papers.items():
            variant_file = variant_candidates_path(root, variant_id, arxiv_id)
            variant_payload = read_json(variant_file) if variant_file.exists() else None
            paper_scores[arxiv_id] = score_paper(
                gold_payload,
                variant_payload,
                strict_rel_tol=args.strict_rel_tol,
                loose_rel_tol=args.loose_rel_tol,
            )
        summary = detection_summary(paper_scores)
        if args.bootstrap > 0:
            summary["bootstrap_ci"] = bootstrap_micro_ci(
                paper_scores, n_resamples=args.bootstrap, seed=args.seed
            )
        detection[variant_id] = summary
        paper_status[variant_id] = paper_status_summary(paper_scores)
        fields[variant_id] = field_summary(paper_scores)

    report = BenchmarkReport(
        schema_version=BENCHMARK_REPORT_SCHEMA_VERSION,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        gold_dir=relative_path(gold_dir(root), workspace=WORKSPACE),
        variant_ids=list(variant_ids),
        paper_ids=sorted(gold_papers),
        tolerances={
            "strict_rel_tol": args.strict_rel_tol,
            "loose_rel_tol": args.loose_rel_tol,
            "bootstrap_resamples": args.bootstrap,
            "seed": args.seed,
        },
        detection=detection,
        paper_status=paper_status,
        fields=fields,
        adjudication_stats=adjudication_stats(root, sorted(gold_papers)),
    )

    write_json(report_json_path(root), json.loads(report.model_dump_json()))
    report_markdown_path(root).parent.mkdir(parents=True, exist_ok=True)
    report_markdown_path(root).write_text(render_markdown(report), encoding="utf-8")
    print(f"report: {report_json_path(root)}")
    print(f"markdown: {report_markdown_path(root)}")
    if skipped:
        print(f"papers without gold: {len(skipped)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
