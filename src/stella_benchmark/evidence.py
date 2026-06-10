"""Resolve candidate source_refs to embedded evidence excerpts.

Excerpts are embedded into alignment JSON at align time so the review server
only ever serves files under benchmark/, never literature/ itself.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from astropy.io import ascii

from .models import ResolvedEcsvEvidence, ResolvedEvidence, ResolvedTextEvidence

MAX_TEXT_LINES = 20


class EvidenceResolver:
    """Resolve text and ECSV-cell source refs with per-file caching."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self._lines: dict[str, list[str] | None] = {}
        self._columns: dict[str, list[str] | None] = {}

    def _lines_for(self, rel_path: str) -> list[str] | None:
        if rel_path not in self._lines:
            path = self.workspace / rel_path
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._lines[rel_path] = None
            else:
                self._lines[rel_path] = text.splitlines()
        return self._lines[rel_path]

    def _columns_for(self, rel_path: str) -> list[str] | None:
        if rel_path not in self._columns:
            path = self.workspace / rel_path
            try:
                table = ascii.read(path, format="ecsv")
            except Exception:
                self._columns[rel_path] = None
            else:
                self._columns[rel_path] = list(table.colnames)
        return self._columns[rel_path]

    def resolve(self, ref: dict[str, Any]) -> ResolvedEvidence:
        if ref.get("kind") == "ecsv_cell":
            return self._resolve_ecsv(ref)
        return self._resolve_text(ref)

    def _resolve_text(self, ref: dict[str, Any]) -> ResolvedTextEvidence:
        rel_path = str(ref.get("path") or "")
        start_line = int(ref.get("start_line") or 0)
        end_line = int(ref.get("end_line") or 0)
        resolved = ResolvedTextEvidence(
            kind="text",
            path=rel_path,
            start_line=start_line,
            end_line=end_line,
            context=str(ref.get("context") or ""),
        )
        lines = self._lines_for(rel_path)
        if lines is None:
            return resolved.model_copy(update={"error": "file not readable"})
        if start_line < 1 or end_line < start_line or end_line > len(lines):
            return resolved.model_copy(
                update={"error": f"invalid line range {start_line}..{end_line} for {len(lines)} lines"}
            )
        excerpt = lines[start_line - 1 : end_line]
        if len(excerpt) > MAX_TEXT_LINES:
            head = MAX_TEXT_LINES // 2
            tail = MAX_TEXT_LINES - head - 1
            excerpt = excerpt[:head] + [f"... ({len(excerpt) - head - tail} lines omitted) ..."] + excerpt[-tail:]
        return resolved.model_copy(update={"lines": excerpt})

    def _resolve_ecsv(self, ref: dict[str, Any]) -> ResolvedEcsvEvidence:
        rel_path = str(ref.get("path") or "")
        line = int(ref.get("line") or 0)
        resolved = ResolvedEcsvEvidence(
            kind="ecsv_cell",
            path=rel_path,
            line=line,
            column=str(ref.get("column") or ""),
            column_header=str(ref.get("column_header") or ""),
            raw_value=str(ref.get("raw_value") or ""),
        )
        lines = self._lines_for(rel_path)
        columns = self._columns_for(rel_path)
        if lines is None or columns is None:
            return resolved.model_copy(update={"error": "ECSV not readable"})
        if line < 1 or line > len(lines):
            return resolved.model_copy(
                update={"error": f"line {line} is outside file bounds 1..{len(lines)}"}
            )
        line_text = lines[line - 1]
        if line_text.startswith("#"):
            return resolved.model_copy(update={"error": "reference points at ECSV metadata"})
        try:
            tokens = shlex.split(line_text)
        except ValueError as exc:
            return resolved.model_copy(update={"error": f"could not parse ECSV row: {exc}"})
        row_cells = {name: tokens[idx] for idx, name in enumerate(columns) if idx < len(tokens)}
        return resolved.model_copy(update={"row_cells": row_cells})

    def data_row_lines(self, rel_path: str) -> list[int]:
        """1-based line numbers of ECSV data rows (excluding metadata and header)."""
        lines = self._lines_for(rel_path)
        columns = self._columns_for(rel_path)
        if lines is None or columns is None:
            return []
        data_lines: list[int] = []
        header_seen = False
        for number, text in enumerate(lines, start=1):
            if text.startswith("#") or not text.strip():
                continue
            if not header_seen:
                header_seen = True
                continue
            data_lines.append(number)
        return data_lines

    def row_cells(self, rel_path: str, line: int) -> dict[str, str]:
        lines = self._lines_for(rel_path)
        columns = self._columns_for(rel_path)
        if lines is None or columns is None or line < 1 or line > len(lines):
            return {}
        try:
            tokens = shlex.split(lines[line - 1])
        except ValueError:
            return {}
        return {name: tokens[idx] for idx, name in enumerate(columns) if idx < len(tokens)}
