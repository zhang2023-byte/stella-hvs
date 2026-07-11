#!/usr/bin/env python3
"""Migrate an external private gold store to structured schema references.

The command is dry-run by default. It never copies gold payloads into the
public workspace; its optional audit report contains paths, statuses and
hashes only.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from stella.benchmark.gold import GoldAnnotation, gold_json_document
from stella.legacy_versions import normalize_legacy_schema
from stella.schema_registry import require_schema, schema_ref

GOLD_DIR_ENV = "STELLA_GOLD_DIR"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def migrate_annotation_yaml(path: Path) -> tuple[bytes, GoldAnnotation]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "schema" in payload:
        require_schema(payload, "benchmark.gold_annotation", require_current=True)
        normalized = copy.deepcopy(payload)
    else:
        normalized = normalize_legacy_schema(payload)
    if normalized["schema"]["name"] != "benchmark.gold_annotation":
        raise ValueError("annotation has the wrong artifact schema")
    annotation = GoldAnnotation.model_validate(normalized)
    rendered = yaml.safe_dump(normalized, sort_keys=False, allow_unicode=True).encode("utf-8")
    return rendered, annotation


def migrate_draft(path: Path) -> bytes:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("payload"), dict):
        raise ValueError("draft must contain a payload object")
    legacy = document.pop("draft_schema", None)
    if legacy is not None:
        if legacy != "stella.benchmark_gold_form_draft.v0.1":
            raise ValueError(f"unknown draft schema: {legacy!r}")
        document["schema"] = schema_ref("benchmark.gold_form_draft")
    else:
        require_schema(document, "benchmark.gold_form_draft", require_current=True)
    if "schema" in document["payload"]:
        require_schema(document["payload"], "benchmark.gold_annotation", require_current=True)
    else:
        document["payload"] = normalize_legacy_schema(document["payload"])
    if document["payload"]["schema"]["name"] != "benchmark.gold_annotation":
        raise ValueError("draft payload has the wrong artifact schema")
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-dir", type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    gold_dir = args.gold_dir or (Path(os.environ[GOLD_DIR_ENV]).expanduser() if os.environ.get(GOLD_DIR_ENV) else None)
    if gold_dir is None or not gold_dir.is_dir():
        raise SystemExit(f"Set {GOLD_DIR_ENV} or pass --gold-dir")

    records: list[dict[str, Any]] = []
    errors = 0
    for yaml_path in sorted(gold_dir.glob("*/annotation_*.yaml")):
        try:
            yaml_bytes, annotation = migrate_annotation_yaml(yaml_path)
            json_path = yaml_path.with_suffix(".json")
            json_bytes = (json.dumps(gold_json_document(annotation), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            for path, rendered in ((yaml_path, yaml_bytes), (json_path, json_bytes)):
                before = path.read_bytes() if path.exists() else b""
                changed = before != rendered
                if args.write and changed:
                    atomic_write(path, rendered)
                records.append({
                    "path": path.relative_to(gold_dir).as_posix(),
                    "status": "changed" if changed else "unchanged",
                    "before_sha256": sha256_bytes(before),
                    "after_sha256": sha256_bytes(rendered),
                })
        except Exception as error:  # audit every file without partial writes
            errors += 1
            records.append({"path": yaml_path.relative_to(gold_dir).as_posix(), "status": "error", "error": str(error)})

    for draft_path in sorted(gold_dir.glob("*/draft_*.json")):
        try:
            rendered = migrate_draft(draft_path)
            before = draft_path.read_bytes()
            changed = before != rendered
            if args.write and changed:
                atomic_write(draft_path, rendered)
            records.append({
                "path": draft_path.relative_to(gold_dir).as_posix(),
                "status": "changed" if changed else "unchanged",
                "before_sha256": sha256_bytes(before),
                "after_sha256": sha256_bytes(rendered),
            })
        except Exception as error:
            errors += 1
            records.append({"path": draft_path.relative_to(gold_dir).as_posix(), "status": "error", "error": str(error)})

    audit = {
        "write": args.write,
        "files": len(records),
        "changed": sum(item["status"] == "changed" for item in records),
        "unchanged": sum(item["status"] == "unchanged" for item in records),
        "errors": errors,
        "records": records,
    }
    if args.report:
        args.report.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: audit[key] for key in ("write", "files", "changed", "unchanged", "errors")}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
