"""Resolve the author TeX manuscript graph (D004) with fail-closed errors (D005).

One root manuscript is identified and its actual include relationships are
followed recursively. The resolver never guesses which TeX files compose the
paper: any ambiguity stops preparation with a structured terminal input error
before any model call. Directive scanning runs on comment-stripped text so
commented-out includes are ignored.

Supported include directives are ``\\input`` and ``\\include`` targeting TeX
files. Non-TeX targets (for example an ``\\input`` of a ``.bbl`` file) are not
part of the manuscript graph; they are reported separately for bibliography
discovery (D032). Other file-inclusion directives (``\\subfile``, ``\\import``,
and similar) are not resolvable unambiguously by this resolver and fail
closed; see the implementation log for the conservative-choice record.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from stella.benchmark.scratch.cleaning import strip_tex_comments

SUPPORTED_INCLUDE_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")
UNSUPPORTED_INCLUDE_RE = re.compile(
    r"\\(?:subfile|subfileinclude|import|subimport|includefrom"
    r"|subincludefrom|InputIfFileExists)\b"
)
DOCUMENTCLASS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\s*\{")
BEGIN_DOCUMENT_RE = re.compile(r"\\begin\{document\}")

MISSING_ROOT = "missing_root_tex"
MULTIPLE_ROOTS = "multiple_root_tex_candidates"
MISSING_INCLUDED = "missing_included_tex"
CYCLIC_INCLUDE = "cyclic_tex_include"
INCLUDE_OUTSIDE = "include_path_outside_paper_directory"
UNDECODABLE = "undecodable_tex_source"
UNSUPPORTED_DIRECTIVE = "unsupported_include_directive"


class TexGraphError(ValueError):
    """One structured terminal input error from D005's fail-closed contract."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class TexSourceFile:
    """Provenance for one manuscript-graph file; paths are model-visible
    block names relative to the paper source directory."""

    path: str
    sha256: str
    line_count: int
    encoding: str


@dataclass
class TexManuscriptGraph:
    root: str
    included: list[str]
    excluded: list[str]
    edges: dict[str, list[str]]
    files: dict[str, TexSourceFile]
    texts: dict[str, str] = field(default_factory=dict)
    non_tex_includes: list[tuple[str, str]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def _decode_source(path: Path, display: str, diagnostics: list[str]) -> tuple[str, str]:
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise TexGraphError(UNDECODABLE, f"{display}: NUL byte in source")
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        diagnostics.append(f"{display}: decoded as latin-1 after utf-8 failure")
        return raw.decode("latin-1"), "latin-1"


def _resolve_include_target(
    source_dir: Path, referring: Path, raw_target: str
) -> Path | None:
    target = raw_target.strip()
    if not target:
        return None
    base = (referring.parent / target).resolve()
    candidates = [base]
    if base.suffix == "":
        candidates.append(base.with_suffix(".tex"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def resolve_tex_graph(source_dir: Path) -> TexManuscriptGraph:
    """Resolve one root TeX manuscript and its recursive include graph."""

    source_dir = source_dir.resolve()
    if not source_dir.is_dir():
        raise TexGraphError(MISSING_ROOT, f"paper source directory not found: {source_dir}")

    tex_paths = sorted(
        path for path in source_dir.rglob("*.tex") if path.is_file()
    )
    diagnostics: list[str] = []
    if not tex_paths:
        raise TexGraphError(MISSING_ROOT, f"no .tex files under {source_dir}")

    display = {path: path.relative_to(source_dir).as_posix() for path in tex_paths}
    decoded: dict[Path, str] = {}
    encodings: dict[Path, str] = {}
    stripped: dict[Path, str] = {}
    for path in tex_paths:
        text, encoding = _decode_source(path, display[path], diagnostics)
        decoded[path] = text
        encodings[path] = encoding
        stripped[path] = strip_tex_comments(text)

    for path in tex_paths:
        match = UNSUPPORTED_INCLUDE_RE.search(stripped[path])
        if match:
            raise TexGraphError(
                UNSUPPORTED_DIRECTIVE,
                f"{display[path]}: unsupported file-inclusion directive "
                f"{match.group(0)!r}",
            )

    roots = [
        path
        for path in tex_paths
        if DOCUMENTCLASS_RE.search(stripped[path]) and BEGIN_DOCUMENT_RE.search(stripped[path])
    ]
    if not roots:
        raise TexGraphError(
            MISSING_ROOT, f"no .tex file with \\documentclass and \\begin{{document}}"
        )
    if len(roots) > 1:
        candidates = sorted(display[path] for path in roots)
        raise TexGraphError(
            MULTIPLE_ROOTS, f"multiple root candidates: {', '.join(candidates)}"
        )
    root = roots[0]

    included: list[Path] = []
    edges: dict[str, list[str]] = {}
    non_tex_includes: list[tuple[str, str]] = []
    visiting: list[Path] = []
    visited: set[Path] = set()

    def visit(path: Path) -> None:
        visiting.append(path)
        visited.add(path)
        included.append(path)
        for match in SUPPORTED_INCLUDE_RE.finditer(stripped[path]):
            raw_target = match.group(1).strip()
            if not raw_target:
                continue
            resolved = _resolve_include_target(source_dir, path, raw_target)
            if resolved is None:
                raise TexGraphError(
                    MISSING_INCLUDED,
                    f"{display[path]}: include target not found: {raw_target!r}",
                )
            try:
                resolved.relative_to(source_dir)
            except ValueError:
                raise TexGraphError(
                    INCLUDE_OUTSIDE,
                    f"{display[path]}: include target escapes the paper "
                    f"source directory: {raw_target!r}",
                ) from None
            target_display = resolved.relative_to(source_dir).as_posix()
            if resolved.suffix.lower() != ".tex":
                non_tex_includes.append((display[path], target_display))
                continue
            edges.setdefault(display[path], []).append(target_display)
            if resolved in visiting:
                cycle = " -> ".join(
                    [display[item] for item in visiting] + [target_display]
                )
                raise TexGraphError(CYCLIC_INCLUDE, f"cyclic include: {cycle}")
            if resolved in visited:
                diagnostics.append(
                    f"{display[path]}: duplicate include of {target_display} skipped"
                )
                continue
            if resolved not in decoded:
                text, encoding = _decode_source(resolved, target_display, diagnostics)
                decoded[resolved] = text
                encodings[resolved] = encoding
                stripped[resolved] = strip_tex_comments(text)
                display[resolved] = target_display
            visit(resolved)
        visiting.pop()

    visit(root)

    included_set = set(included)
    excluded = sorted(
        path.relative_to(source_dir).as_posix()
        for path in source_dir.rglob("*.tex")
        if path.is_file() and path.resolve() not in included_set
    )

    files: dict[str, TexSourceFile] = {}
    texts: dict[str, str] = {}
    for path in included:
        name = display[path]
        text = decoded[path]
        files[name] = TexSourceFile(
            path=name,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            line_count=len(text.split("\n")) - (1 if text.endswith("\n") else 0),
            encoding=encodings[path],
        )
        texts[name] = text

    return TexManuscriptGraph(
        root=display[root],
        included=[display[path] for path in included],
        excluded=excluded,
        edges=edges,
        files=files,
        texts=texts,
        non_tex_includes=non_tex_includes,
        diagnostics=diagnostics,
    )
