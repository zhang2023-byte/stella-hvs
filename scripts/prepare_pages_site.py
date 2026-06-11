#!/usr/bin/env python3
"""Prepare the GitHub Pages publish directory from the static catalog site."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = WORKSPACE / "catalog" / "web" / "static"
DEFAULT_PAGES_DIR = WORKSPACE / "pages"
EXCLUDED_NAMES = {".DS_Store"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy catalog/web/static into the GitHub Pages site directory."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Generated static HTML directory. Default: catalog/web/static.",
    )
    parser.add_argument(
        "--pages-dir",
        type=Path,
        default=DEFAULT_PAGES_DIR,
        help="GitHub Pages publish directory. Default: pages.",
    )
    return parser


def _resolve_for_safety(path: Path) -> Path:
    return path.expanduser().resolve()


def _validate_paths(source: Path, pages_dir: Path) -> tuple[Path, Path]:
    source = _resolve_for_safety(source)
    pages_dir = _resolve_for_safety(pages_dir)
    if not source.exists():
        raise FileNotFoundError(f"static site source does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"static site source is not a directory: {source}")
    if not (source / "index.html").exists():
        raise FileNotFoundError(f"static site source is missing index.html: {source}")
    if source == pages_dir:
        raise ValueError("source and pages-dir must be different directories")
    if pages_dir == WORKSPACE:
        raise ValueError("refusing to replace the repository root")
    if pages_dir == Path(pages_dir.anchor):
        raise ValueError("refusing to replace a filesystem root")
    if source.is_relative_to(pages_dir) or pages_dir.is_relative_to(source):
        raise ValueError("source and pages-dir must not contain each other")
    return source, pages_dir


def prepare_pages_site(source: Path, pages_dir: Path) -> Path:
    source, pages_dir = _validate_paths(source, pages_dir)
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True)
    for item in sorted(source.iterdir()):
        if item.name in EXCLUDED_NAMES:
            continue
        target = pages_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(*EXCLUDED_NAMES))
        else:
            shutil.copy2(item, target)
    (pages_dir / ".nojekyll").write_text("", encoding="utf-8")
    if not (pages_dir / "index.html").exists():
        raise FileNotFoundError(f"prepared site is missing index.html: {pages_dir}")
    return pages_dir


def main() -> int:
    args = build_parser().parse_args()
    pages_dir = prepare_pages_site(args.source, args.pages_dir)
    print(f"Prepared GitHub Pages site: {pages_dir}")
    print("Publish by committing pages/ and pushing to main.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
