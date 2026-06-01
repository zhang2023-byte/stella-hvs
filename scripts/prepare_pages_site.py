#!/usr/bin/env python3
"""Prepare the GitHub Pages publish directory from the static catalog site."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = WORKSPACE / "catalog" / "html" / "static"
DEFAULT_SITE_DIR = WORKSPACE / "site"
EXCLUDED_NAMES = {".DS_Store"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Copy catalog/html/static into the GitHub Pages site directory."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Generated static HTML directory. Default: catalog/html/static.",
    )
    parser.add_argument(
        "--site-dir",
        type=Path,
        default=DEFAULT_SITE_DIR,
        help="GitHub Pages publish directory. Default: site.",
    )
    return parser


def _resolve_for_safety(path: Path) -> Path:
    return path.expanduser().resolve()


def _validate_paths(source: Path, site_dir: Path) -> tuple[Path, Path]:
    source = _resolve_for_safety(source)
    site_dir = _resolve_for_safety(site_dir)
    if not source.exists():
        raise FileNotFoundError(f"static site source does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"static site source is not a directory: {source}")
    if not (source / "index.html").exists():
        raise FileNotFoundError(f"static site source is missing index.html: {source}")
    if source == site_dir:
        raise ValueError("source and site-dir must be different directories")
    if site_dir == WORKSPACE:
        raise ValueError("refusing to replace the repository root")
    if site_dir == Path(site_dir.anchor):
        raise ValueError("refusing to replace a filesystem root")
    if source.is_relative_to(site_dir) or site_dir.is_relative_to(source):
        raise ValueError("source and site-dir must not contain each other")
    return source, site_dir


def prepare_pages_site(source: Path, site_dir: Path) -> Path:
    source, site_dir = _validate_paths(source, site_dir)
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)
    for item in sorted(source.iterdir()):
        if item.name in EXCLUDED_NAMES:
            continue
        target = site_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns(*EXCLUDED_NAMES))
        else:
            shutil.copy2(item, target)
    (site_dir / ".nojekyll").write_text("", encoding="utf-8")
    if not (site_dir / "index.html").exists():
        raise FileNotFoundError(f"prepared site is missing index.html: {site_dir}")
    return site_dir


def main() -> int:
    args = build_parser().parse_args()
    site_dir = prepare_pages_site(args.source, args.site_dir)
    print(f"Prepared GitHub Pages site: {site_dir}")
    print("Publish by committing site/ and pushing to main.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
