"""Deterministic context packing for benchmark extraction runs.

The interactive agent reads paper files ad hoc, so nobody can say afterwards
what the model actually saw. The benchmark pipeline instead packs a paper's
inputs into one deterministic text block and records a SHA-256 per file and
for the whole pack: two runs over the same archive see byte-identical
context, and the run archive can prove it.

Packing rules (fixed, version-bumped if they ever change):

1. ``catalog_review.json`` and ``catalog_extraction.json`` verbatim.
2. ECSV tables in ``inputs.ecsv_paths`` order (the same rule the skeleton
   uses), with 1-based physical line numbers — ECSV cell source refs need
   exact line numbers.
3. All ``*.tex``, ``*.bbl``, ``*.bib`` files under ``arxiv_source/`` in
   sorted relative-path order, line-numbered — text source refs need exact
   line ranges, citation records need bibliography lines.

Line numbers use the ``N|`` prefix; the prompt explains this convention to
the model. There is no silent truncation: a pack exceeding the hard budget
raises, because a model that saw half a paper produces structurally valid
but scientifically wrong output.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

PACKER_VERSION = "stella.benchmark_context_pack.v0.1"

# ~700K tokens at roughly 3.5 chars/token; far above the pilot papers and
# inside deepseek-v4-pro's 1M context. Oversized papers fail loudly.
DEFAULT_MAX_CHARS = 2_500_000

TEXT_SOURCE_SUFFIXES = (".tex", ".bbl", ".bib")


@dataclass(frozen=True)
class PackedFile:
    path: str
    kind: str
    chars: int
    lines: int
    sha256: str


@dataclass
class PackedContext:
    text: str
    files: list[PackedFile] = field(default_factory=list)
    sha256: str = ""
    total_chars: int = 0

    def manifest(self) -> dict:
        return {
            "packer_version": PACKER_VERSION,
            "sha256": self.sha256,
            "total_chars": self.total_chars,
            "files": [vars(item) for item in self.files],
        }


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def numbered_lines(text: str) -> str:
    """Prefix each physical line with its 1-based number (``N|line``)."""

    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return "\n".join(f"{index}|{line}" for index, line in enumerate(lines, 1))


def _section(header: str, body: str) -> str:
    return f"===== BEGIN {header} =====\n{body}\n===== END {header} =====\n"


def pack_paper_context(
    workspace: Path,
    arxiv_id: str,
    ecsv_paths: list[str],
    *,
    literature_dir: Path | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> PackedContext:
    """Pack one paper's pipeline-visible inputs into a deterministic block.

    ``ecsv_paths`` comes from the skeleton's ``inputs.ecsv_paths`` so the
    packed tables and the document's declared inputs cannot diverge.
    """

    literature_dir = literature_dir or workspace / "literature"
    paper_dir = literature_dir / arxiv_id
    if not paper_dir.is_dir():
        raise FileNotFoundError(f"paper directory not found: {paper_dir}")

    entries: list[tuple[str, str, str]] = []  # (kind, relpath, body)

    for kind, name in (
        ("catalog_review", "catalog_review.json"),
        ("catalog_extraction", "catalog_extraction.json"),
    ):
        path = paper_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"required input missing: {path}")
        relpath = path.relative_to(workspace).as_posix()
        entries.append((kind, relpath, path.read_text(encoding="utf-8")))

    for ecsv_rel in ecsv_paths:
        path = workspace / ecsv_rel
        if not path.is_file():
            raise FileNotFoundError(f"declared ECSV missing: {path}")
        entries.append(
            ("ecsv_table", ecsv_rel, numbered_lines(path.read_text(encoding="utf-8")))
        )

    source_dir = paper_dir / "arxiv_source"
    if source_dir.is_dir():
        for path in sorted(source_dir.rglob("*")):
            if path.suffix.lower() not in TEXT_SOURCE_SUFFIXES or not path.is_file():
                continue
            relpath = path.relative_to(workspace).as_posix()
            entries.append(
                (
                    "paper_text",
                    relpath,
                    numbered_lines(
                        path.read_text(encoding="utf-8", errors="replace")
                    ),
                )
            )

    files: list[PackedFile] = []
    sections: list[str] = []
    for kind, relpath, body in entries:
        files.append(
            PackedFile(
                path=relpath,
                kind=kind,
                chars=len(body),
                lines=body.count("\n") + 1 if body else 0,
                sha256=_sha256(body),
            )
        )
        sections.append(_section(relpath, body))

    text = "\n".join(sections)
    if len(text) > max_chars:
        raise ValueError(
            f"packed context for {arxiv_id} is {len(text)} chars, over the "
            f"{max_chars} budget; refusing silent truncation (split or "
            "raise the budget deliberately)"
        )
    return PackedContext(
        text=text,
        files=files,
        sha256=_sha256(text),
        total_chars=len(text),
    )


def packed_context_summary(context: PackedContext) -> str:
    lines = [f"packed {len(context.files)} files, {context.total_chars} chars, sha {context.sha256[:12]}"]
    for item in context.files:
        lines.append(f"  {item.kind:18} {item.path} ({item.chars} chars)")
    return "\n".join(lines)


def dump_manifest(context: PackedContext, path: Path) -> None:
    path.write_text(
        json.dumps(context.manifest(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
