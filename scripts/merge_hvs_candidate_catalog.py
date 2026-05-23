#!/usr/bin/env python3
"""Merge paper-level HVS candidates into the object-level catalog/ directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
SRC = WORKSPACE / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from high_velocity_lit.hvs_candidate_catalog import (  # noqa: E402
    HVS_CANDIDATES_FILENAME,
    write_rebuilt_hvs_candidate_catalog,
    write_updated_hvs_candidate_catalog,
)


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected True or False")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or update catalog/ object-level HVS candidate JSON files."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rebuild = subparsers.add_parser("rebuild", help="Rebuild catalog/ from all literature_hvs_candidates.json files.")
    rebuild.add_argument(
        "--literature-dir",
        type=Path,
        default=WORKSPACE / "literature",
        help="Literature root directory to scan. Default: literature/",
    )
    rebuild.add_argument(
        "--catalog-dir",
        type=Path,
        default=WORKSPACE / "catalog",
        help="Object catalog output directory. Default: catalog/",
    )
    rebuild.add_argument("--dry-run", type=parse_bool, default=False, help="Print planned writes without writing files.")
    rebuild.add_argument(
        "--fail-on-skipped",
        action="store_true",
        help="Exit non-zero if any malformed paper-level input is skipped.",
    )

    update = subparsers.add_parser("update", help="Merge one paper-level HVS candidates JSON into catalog/.")
    update.add_argument(
        "--arxiv-id",
        default="",
        help="arXiv ID whose literature/<arxiv-id>/literature_hvs_candidates.json should be merged.",
    )
    update.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Explicit path to a literature_hvs_candidates.json file.",
    )
    update.add_argument(
        "--literature-dir",
        type=Path,
        default=WORKSPACE / "literature",
        help="Literature root directory. Default: literature/",
    )
    update.add_argument(
        "--catalog-dir",
        type=Path,
        default=WORKSPACE / "catalog",
        help="Object catalog output directory. Default: catalog/",
    )
    update.add_argument("--dry-run", type=parse_bool, default=False, help="Print planned writes without writing files.")
    update.add_argument(
        "--fail-on-skipped",
        action="store_true",
        help="Exit non-zero if any malformed paper-level input or catalog object is skipped.",
    )
    return parser


def _candidate_path_from_args(args: argparse.Namespace) -> Path:
    if args.path is not None and args.arxiv_id:
        raise argparse.ArgumentTypeError("use either --path or --arxiv-id, not both")
    if args.path is not None:
        return args.path.expanduser()
    if args.arxiv_id:
        return args.literature_dir.expanduser() / args.arxiv_id / HVS_CANDIDATES_FILENAME
    raise argparse.ArgumentTypeError("update requires --path or --arxiv-id")


def _print_common_result(prefix: str, result: dict[str, object]) -> None:
    index_record = result["index_record"]  # type: ignore[index]
    summary = index_record["summary"]  # type: ignore[index]
    dry_run = result.get("dry_run") is True
    if dry_run:
        action = "Would update" if prefix == "Updated" else "Would build"
    else:
        action = prefix
    print(
        f"{action} HVS candidate object catalog: "
        f"{summary['object_count']} objects, "
        f"{summary['source_count']} sources, "
        f"{summary['warning_count']} warnings, "
        f"{summary['skipped_count']} skipped inputs."
    )
    if dry_run:
        print("Planned writes:")
        for path in result.get("planned_write_paths") or []:
            print(f"  {path}")
        planned_delete_paths = result.get("planned_delete_paths") or []
        if planned_delete_paths:
            print("Planned deletes:")
            for path in planned_delete_paths:
                print(f"  {path}")
    else:
        for path in result.get("written_paths") or []:
            print(path)
        deleted_paths = result.get("deleted_paths") or []
        if deleted_paths:
            print("Deleted stale object files:")
            for path in deleted_paths:
                print(f"  {path}")


def _fail_if_skipped(result: dict[str, object]) -> int:
    skipped = result.get("skipped") or []
    if not skipped:
        return 0
    print("Skipped malformed HVS catalog inputs:", file=sys.stderr)
    for item in skipped:
        if isinstance(item, dict):
            print(f"  {item.get('path')}: {item.get('error')}", file=sys.stderr)
        else:
            print(f"  {item}", file=sys.stderr)
    return 1


def main() -> int:
    parser = build_parser()
    try:
        args = parser.parse_args()
        literature_dir = args.literature_dir.expanduser()
        catalog_dir = args.catalog_dir.expanduser()
        if args.command == "rebuild":
            result = write_rebuilt_hvs_candidate_catalog(
                literature_dir,
                catalog_dir,
                workspace=WORKSPACE,
                dry_run=args.dry_run,
            )
            _print_common_result("Built", result)
            if args.fail_on_skipped:
                return _fail_if_skipped(result)
            return 0

        candidate_path = _candidate_path_from_args(args)
        result = write_updated_hvs_candidate_catalog(
            candidate_path,
            catalog_dir,
            literature_dir=literature_dir,
            workspace=WORKSPACE,
            dry_run=args.dry_run,
        )
        _print_common_result("Updated", result)
        print(
            "Update input: "
            f"{result['new_candidate_count']} new candidate records, "
            f"{result['replaced_existing_source_count']} replaced existing source records."
        )
        if args.fail_on_skipped:
            return _fail_if_skipped(result)
        return 0
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
