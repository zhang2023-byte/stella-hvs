"""Immutable, value-free selection of one expert gold annotation per paper."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from stella.benchmark.campaign import papers_for_split, sha256_file
from stella.benchmark.gold import (
    GoldAnnotation,
    gold_json_document,
    validate_annotator_handle,
)
from stella.benchmark.paths import validate_path_segment
from stella.benchmark.run_contract import canonical_sha256
from stella.schema_registry import (
    require_campaign_writable,
    require_schema,
    schema_ref,
)


DEFAULT_CONTRIBUTION_SELECTIONS = {
    "dev10": "contribution-dev-primary-v2",
    "full50": "contribution-full-primary-v1",
}


def contribution_selection_id(
    payload: dict[str, Any] | None, *, profile: str = "dev10"
) -> str:
    """Resolve one immutable contribution selection from request data."""

    requested = str((payload or {}).get("gold_selection_id") or "")
    if not requested:
        requested = str((payload or {}).get("selection_id") or "")
    if not requested:
        try:
            requested = DEFAULT_CONTRIBUTION_SELECTIONS[profile]
        except KeyError as error:
            raise ValueError(f"unknown benchmark profile: {profile}") from error
    return validate_path_segment(requested, "gold selection id")


def contribution_selection_path(
    root: Path, payload: dict[str, Any] | None, *, profile: str = "dev10"
) -> Path:
    selection_id = contribution_selection_id(payload, profile=profile)
    return Path(root) / "benchmark" / "gold_selections" / f"{selection_id}.json"


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return payload


def _expected_relative(arxiv_id: str, annotator: str, suffix: str) -> str:
    return f"{arxiv_id}/annotation_{annotator}.{suffix}"


def _records_by_file(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    require_schema(manifest, "benchmark.gold_manifest", require_current=True)
    records: dict[str, dict[str, Any]] = {}
    for record in manifest.get("files") or []:
        if not isinstance(record, dict):
            raise ValueError("gold manifest files must contain objects")
        relative = str(record.get("file") or "")
        if not relative or relative in records:
            raise ValueError(f"duplicate or empty gold manifest file: {relative!r}")
        records[relative] = record
    return records


def _verify_file_record(gold_dir: Path, record: dict[str, Any]) -> Path:
    relative = str(record.get("file") or "")
    path = gold_dir / relative
    if not path.is_file():
        raise ValueError(f"private gold file is missing: {relative}")
    if sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"private gold file hash mismatch: {relative}")
    if path.stat().st_size != int(record.get("bytes") or -1):
        raise ValueError(f"private gold file byte count mismatch: {relative}")
    return path


def validate_annotation_twin(
    gold_dir: Path,
    *,
    arxiv_id: str,
    annotator: str,
    yaml_record: dict[str, Any],
    json_record: dict[str, Any],
) -> None:
    """Verify one manifest-pinned YAML and its deterministic JSON twin."""

    safe_arxiv_id = validate_path_segment(arxiv_id, "paper id")
    safe_annotator = validate_annotator_handle(annotator)
    expected_yaml = _expected_relative(safe_arxiv_id, safe_annotator, "yaml")
    expected_json = _expected_relative(safe_arxiv_id, safe_annotator, "json")
    if yaml_record.get("file") != expected_yaml:
        raise ValueError(f"selected YAML path must be {expected_yaml}")
    if json_record.get("file") != expected_json:
        raise ValueError(f"selected JSON path must be {expected_json}")
    for record in (yaml_record, json_record):
        if str(record.get("arxiv_id") or "") != safe_arxiv_id:
            raise ValueError(f"gold manifest arxiv_id mismatch: {record.get('file')}")

    yaml_path = _verify_file_record(gold_dir, yaml_record)
    json_path = _verify_file_record(gold_dir, json_record)
    try:
        yaml_payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"private gold YAML is invalid: {expected_yaml}") from exc
    if not isinstance(yaml_payload, dict):
        raise ValueError(f"private gold YAML must be a mapping: {expected_yaml}")
    annotation = GoldAnnotation.model_validate(yaml_payload)
    if annotation.arxiv_id != safe_arxiv_id or annotation.annotator != safe_annotator:
        raise ValueError(f"private gold YAML identity mismatch: {expected_yaml}")
    json_payload = _load_json_object(json_path, label="private gold JSON twin")
    if (
        str(json_payload.get("arxiv_id") or "") != safe_arxiv_id
        or str(json_payload.get("annotator") or "") != safe_annotator
    ):
        raise ValueError(f"private gold JSON identity mismatch: {expected_json}")
    if json_payload != gold_json_document(annotation):
        raise ValueError(f"private gold is not the deterministic JSON twin: {expected_json}")


def _manifest_twins(
    manifest: dict[str, Any],
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    by_file = _records_by_file(manifest)
    twins: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for relative, record in by_file.items():
        path = Path(relative)
        if len(path.parts) != 2 or path.suffix not in {".yaml", ".json"}:
            raise ValueError(f"invalid gold annotation manifest path: {relative}")
        arxiv_id = path.parent.name
        prefix = "annotation_"
        if not path.stem.startswith(prefix):
            raise ValueError(f"invalid gold annotation manifest path: {relative}")
        annotator = validate_annotator_handle(path.stem[len(prefix) :])
        key = (arxiv_id, annotator)
        kind = path.suffix[1:]
        bucket = twins.setdefault(key, {})
        if kind in bucket:
            raise ValueError(f"duplicate {kind} gold twin: {relative}")
        bucket[kind] = record
    return twins


def validate_gold_manifest_twins(gold_dir: Path, manifest: dict[str, Any]) -> None:
    """Require every formal annotation in a manifest to be a valid twin pair."""

    for (arxiv_id, annotator), twin in _manifest_twins(manifest).items():
        missing = sorted({"yaml", "json"} - set(twin))
        if missing:
            raise ValueError(
                f"gold annotation {arxiv_id}/{annotator} is missing twin: {', '.join(missing)}"
            )
        validate_annotation_twin(
            gold_dir,
            arxiv_id=arxiv_id,
            annotator=annotator,
            yaml_record=twin["yaml"],
            json_record=twin["json"],
        )


def build_gold_selection(
    *,
    campaign_path: Path,
    gold_manifest_path: Path,
    gold_dir: Path,
    split: str,
    selection_id: str,
    annotator_map: dict[str, str],
) -> dict[str, Any]:
    """Build one immutable public profile without copying private gold values."""

    safe_selection_id = validate_path_segment(selection_id, "gold selection id")
    campaign = _load_json_object(campaign_path, label="campaign manifest")
    require_schema(campaign, "benchmark.campaign", require_current=True)
    campaign_id = require_campaign_writable(str(campaign.get("campaign_id") or ""))
    expected = papers_for_split(campaign, split)
    supplied = set(annotator_map)
    missing = sorted(set(expected) - supplied)
    extra = sorted(supplied - set(expected))
    if missing or extra:
        parts = []
        if missing:
            parts.append("missing: " + ", ".join(missing))
        if extra:
            parts.append("extra: " + ", ".join(extra))
        raise ValueError("annotator map must exactly cover the split; " + "; ".join(parts))

    manifest = _load_json_object(gold_manifest_path, label="gold manifest")
    validate_gold_manifest_twins(gold_dir, manifest)
    twins = _manifest_twins(manifest)
    papers: list[dict[str, Any]] = []
    for arxiv_id in expected:
        annotator = validate_annotator_handle(annotator_map[arxiv_id])
        twin = twins.get((arxiv_id, annotator))
        if twin is None:
            raise ValueError(
                f"selected gold is missing: {_expected_relative(arxiv_id, annotator, 'json')}"
            )
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "annotator": annotator,
                "yaml": dict(twin["yaml"]),
                "json": dict(twin["json"]),
            }
        )
    return {
        "schema": schema_ref("benchmark.gold_selection"),
        "selection_id": safe_selection_id,
        "campaign": {
            "campaign_id": campaign_id,
            "sha256": sha256_file(campaign_path),
        },
        "split": split,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_gold_manifest_sha256": sha256_file(gold_manifest_path),
        "selected_records_sha256": canonical_sha256(papers),
        "papers": papers,
    }


def load_gold_selection_snapshot(
    *,
    selection_path: Path,
    gold_manifest_path: Path,
    gold_dir: Path,
    paper_ids: list[str],
    campaign_id: str,
    campaign_sha256: str,
    split: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Load exactly the selected expert document for every scored paper."""

    profile = _load_json_object(selection_path, label="gold selection manifest")
    require_schema(profile, "benchmark.gold_selection", require_current=True)
    selection_id = validate_path_segment(
        str(profile.get("selection_id") or ""), "gold selection id"
    )
    expected_campaign = {
        "campaign_id": campaign_id,
        "sha256": campaign_sha256,
    }
    if profile.get("campaign") != expected_campaign:
        raise ValueError("gold selection campaign binding does not match scoring campaign")
    if profile.get("split") != split:
        raise ValueError("gold selection split does not match requested split")
    papers = profile.get("papers")
    if not isinstance(papers, list) or [
        str(paper.get("arxiv_id") or "") if isinstance(paper, dict) else ""
        for paper in papers
    ] != paper_ids:
        raise ValueError("gold selection papers must match the exact campaign split order")
    selected_records_sha256 = canonical_sha256(papers)
    if profile.get("selected_records_sha256") != selected_records_sha256:
        raise ValueError("gold selection selected-records hash mismatch")

    manifest = _load_json_object(gold_manifest_path, label="gold manifest")
    current_records = _records_by_file(manifest)
    annotations: dict[str, dict[str, Any]] = {}
    annotators: dict[str, str] = {}
    for arxiv_id, paper in zip(paper_ids, papers, strict=True):
        if not isinstance(paper, dict):
            raise ValueError(f"gold selection paper must be an object: {arxiv_id}")
        annotator = validate_annotator_handle(str(paper.get("annotator") or ""))
        selected: dict[str, dict[str, Any]] = {}
        for kind in ("yaml", "json"):
            record = paper.get(kind)
            if not isinstance(record, dict):
                raise ValueError(f"gold selection {arxiv_id}/{annotator} is missing {kind}")
            expected_file = _expected_relative(arxiv_id, annotator, kind)
            if record.get("file") != expected_file:
                raise ValueError(f"gold selection {kind} path must be {expected_file}")
            current = current_records.get(expected_file)
            if current is None:
                raise ValueError(f"selected gold is absent from gold manifest: {expected_file}")
            for field in ("arxiv_id", "file", "sha256", "bytes"):
                if record.get(field) != current.get(field):
                    raise ValueError(
                        f"gold selection record does not match gold manifest: {expected_file}"
                    )
            selected[kind] = current
        validate_annotation_twin(
            gold_dir,
            arxiv_id=arxiv_id,
            annotator=annotator,
            yaml_record=selected["yaml"],
            json_record=selected["json"],
        )
        json_path = gold_dir / str(selected["json"]["file"])
        annotations[arxiv_id] = _load_json_object(
            json_path, label="private gold JSON twin"
        )
        annotators[arxiv_id] = annotator

    snapshot = {
        "selection_id": selection_id,
        "manifest_sha256": sha256_file(selection_path),
        "selected_records_sha256": selected_records_sha256,
        "gold_manifest_sha256": sha256_file(gold_manifest_path),
        "source_gold_manifest_sha256": str(
            profile.get("source_gold_manifest_sha256") or ""
        ),
        "annotators": annotators,
    }
    return annotations, snapshot


def write_gold_selection_once(path: Path, profile: dict[str, Any]) -> Path:
    require_schema(profile, "benchmark.gold_selection", require_current=True)
    selection_id = validate_path_segment(
        str(profile.get("selection_id") or ""), "gold selection id"
    )
    if path.name != f"{selection_id}.json":
        raise ValueError("gold selection filename must match selection_id")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as exc:
        raise ValueError(f"gold selection already exists: {path}") from exc
    return path


def prepare_selection(payload: dict, *, root: Path, paper_id: str | None = None) -> dict:
    """gold.prepare_selection adapter: public, value-free selection profile."""

    import os

    from stella.workflows import operation_complete, operation_failed

    gold_dir = os.environ.get("STELLA_GOLD_DIR", "")
    if not gold_dir:
        return operation_failed(
            "STELLA_GOLD_DIR is required to read the selected experts",
            kind="precondition",
        )
    raw_papers = (payload or {}).get("papers") or []
    try:
        papers = [validate_path_segment(str(paper), "paper id") for paper in raw_papers]
        expert = validate_annotator_handle(str((payload or {}).get("expert") or ""))
    except ValueError as error:
        return operation_failed(str(error), kind="validation")
    if not papers:
        return operation_failed(
            "selection requires at least one paper", kind="precondition"
        )
    try:
        selection_id = contribution_selection_id(payload)
    except ValueError as error:
        return operation_failed(str(error), kind="validation")
    selection = {
        "schema": schema_ref("benchmark.hvs_contribution_gold_selection"),
        "selection_id": selection_id,
        "target_schema": schema_ref("benchmark.hvs_contribution_annotation"),
        "papers": [],
    }
    resolved_gold_dir = Path(gold_dir).expanduser().resolve()
    for paper in papers:
        annotation = resolved_gold_dir / paper / f"annotation_{expert}.json"
        if not annotation.is_file():
            return operation_failed(
                f"missing annotation for {paper} and expert {expert}",
                kind="precondition",
            )
        try:
            annotation_document = _load_json_object(
                annotation, label="selected contribution Gold"
            )
            require_schema(
                annotation_document,
                "benchmark.hvs_contribution_annotation",
                require_current=True,
            )
            from stella.benchmark.hvs_contribution_gold import (
                validate_contribution_gold_annotation,
            )

            validate_contribution_gold_annotation(
                annotation_document, require_current=True
            )
        except Exception as error:  # noqa: BLE001 - public selection fails closed.
            return operation_failed(
                f"invalid current contribution Gold for {paper}/{expert}: {error}",
                kind="validation",
            )
        selection["papers"].append(
            {
                "arxiv_id": paper,
                "selected_expert": expert,
                "annotation_file": f"annotation_{expert}.json",
                "sha256": sha256_file(annotation),
            }
        )
    selection_path = contribution_selection_path(root, payload)
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with selection_path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(selection, indent=2, sort_keys=True) + "\n")
    except FileExistsError:
        return operation_failed(
            f"gold selection already exists: {selection_path}",
            kind="precondition",
            next_action="use the existing immutable selection or choose a new release",
        )
    return operation_complete(
        artifacts=[str(selection_path)],
        selection=selection,
        value_free=True,
    )


def validate_selection(payload: dict, result: dict, *, root: Path) -> list[str]:
    """A completed selection must be a value-free public artifact."""

    if result.get("status") != "complete":
        return []
    try:
        selection_path = contribution_selection_path(root, payload)
    except ValueError as error:
        return [str(error)]
    if not selection_path.is_file():
        return [f"selection reported complete but {selection_path} is missing"]
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
    except ValueError as error:
        return [f"selection artifact is not parseable: {error}"]
    try:
        require_schema(
            selection,
            "benchmark.hvs_contribution_gold_selection",
            require_current=True,
        )
    except ValueError as error:
        return [f"invalid contribution gold selection schema: {error}"]
    if selection.get("selection_id") != selection_path.stem:
        return ["selection id must match its immutable filename"]
    try:
        require_schema(
            {"schema": selection.get("target_schema")},
            "benchmark.hvs_contribution_annotation",
        )
    except ValueError as error:
        return [f"selection target schema must be readable contribution Gold: {error}"]
    papers = selection.get("papers") if isinstance(selection, dict) else None
    if not isinstance(papers, list) or not papers:
        return ["selection artifact must list papers"]
    forbidden_value_keys = (
        "values",
        "quantities",
        "measurements",
        "gold_values",
    )
    for entry in papers:
        if not isinstance(entry, dict):
            return ["selection entries must be objects"]
        hit = sorted(set(entry) & set(forbidden_value_keys))
        if hit:
            return [f"selection entry carries gold values: {hit}"]
        if not entry.get("sha256"):
            return ["selection entries must carry annotation hashes"]
    return []
