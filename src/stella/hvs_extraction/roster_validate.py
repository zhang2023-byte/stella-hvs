"""Deterministic roster evidence validation and source hydration (D012, D015).

The model selects evidence coordinates; code validates the coordinates and
resolves their exact text but never moves a reference to different lines or
replaces it with scientifically preferred evidence. Validation errors carry
exact JSON paths and mechanically verified facts only — they never claim that
candidate membership is scientifically wrong (D017).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stella.hvs_extraction.range_expand import expand_range_notation


SOURCE_PATH_NOT_ALLOWED = "source_path_not_allowed"
SOURCE_LINE_RANGE_REVERSED = "source_line_range_reversed"
SOURCE_LINE_OUT_OF_BOUNDS = "source_line_out_of_bounds"
SOURCE_RANGE_COMMENT_ONLY = "source_range_comment_only"
IDENTIFIER_NOT_VERBATIM = "identifier_not_verbatim"
DUPLICATE_IDENTIFIER_WITHIN_CANDIDATE = "duplicate_identifier_within_candidate"
DUPLICATE_IDENTIFIER_ACROSS_CANDIDATES = "duplicate_identifier_across_candidates"
RANGE_NOTATION_NOT_VERBATIM = "range_notation_not_verbatim"
RANGE_NOTATION_UNPARSEABLE = "range_notation_unparseable"


@dataclass(frozen=True)
class EvidenceIssue:
    path: str
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}: {self.code}: {self.message}"


def _file_lines(texts: dict[str, str], path: str) -> list[str]:
    lines = texts[path].split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def resolve_source_range(texts: dict[str, str], path: str, start: int, end: int) -> str:
    """Return the exact original lines for one validated inclusive range."""

    lines = _file_lines(texts, path)
    return "\n".join(lines[start - 1 : end])


def _iter_source_refs(payload: dict[str, Any]):
    """Yield (json_path, ref, owner) for every model-submitted source ref."""

    for ci, candidate in enumerate(payload.get("candidates") or []):
        for ii, identifier in enumerate(candidate.get("identifiers") or []):
            base = f"$.candidates[{ci}].identifiers[{ii}]"
            for ri, ref in enumerate(identifier.get("source_refs") or []):
                yield f"{base}.source_refs[{ri}]", ref, ("identifier", ci, ii)
        qualification = candidate.get("qualification") or {}
        for ri, ref in enumerate(qualification.get("source_refs") or []):
            yield f"$.candidates[{ci}].qualification.source_refs[{ri}]", ref, ("qualification", ci, None)
    for ei, exclusion in enumerate(payload.get("reviewed_exclusions") or []):
        for ri, ref in enumerate(exclusion.get("source_refs") or []):
            yield f"$.reviewed_exclusions[{ei}].source_refs[{ri}]", ref, ("exclusion", ei, None)
    for gi, group in enumerate(payload.get("range_groups") or []):
        for ri, ref in enumerate(group.get("source_refs") or []):
            yield f"$.range_groups[{gi}].source_refs[{ri}]", ref, ("range_group", gi, None)
        qualification = group.get("qualification") or {}
        for ri, ref in enumerate(qualification.get("source_refs") or []):
            yield f"$.range_groups[{gi}].qualification.source_refs[{ri}]", ref, ("range_group_qualification", gi, None)


def validate_roster_submission(
    payload: dict[str, Any],
    *,
    file_line_counts: dict[str, int],
    original_texts: dict[str, str],
    cleaned_texts: dict[str, str],
) -> list[EvidenceIssue]:
    """Run every deterministic source-coordinate, identifier, and duplicate check."""

    issues: list[EvidenceIssue] = []
    for path, ref, _owner in _iter_source_refs(payload):
        file_path = ref.get("path")
        start = ref.get("start_line")
        end = ref.get("end_line")
        if file_path not in file_line_counts:
            issues.append(
                EvidenceIssue(path, SOURCE_PATH_NOT_ALLOWED, f"path {file_path!r} is not a TeX file in the approved manuscript graph")
            )
            continue
        if not (isinstance(start, int) and isinstance(end, int)) or isinstance(start, bool) or isinstance(end, bool):
            issues.append(EvidenceIssue(path, SOURCE_LINE_OUT_OF_BOUNDS, "line values must be integers"))
            continue
        if start > end:
            issues.append(
                EvidenceIssue(path, SOURCE_LINE_RANGE_REVERSED, f"start_line {start} exceeds end_line {end}")
            )
            continue
        line_count = file_line_counts[file_path]
        if start < 1 or end > line_count:
            issues.append(
                EvidenceIssue(path, SOURCE_LINE_OUT_OF_BOUNDS, f"range {start}-{end} is outside {file_path} (1-{line_count})")
            )
            continue
        cleaned_lines = _file_lines(cleaned_texts, file_path)
        if all(not line.strip() for line in cleaned_lines[start - 1 : end]):
            issues.append(
                EvidenceIssue(path, SOURCE_RANGE_COMMENT_ONLY, f"range {start}-{end} in {file_path} points only to content removed from the model-facing view")
            )

    seen_per_candidate: list[dict[str, int]] = []
    first_owner: dict[str, int] = {}
    for ci, candidate in enumerate(payload.get("candidates") or []):
        within: dict[str, int] = {}
        for ii, identifier in enumerate(candidate.get("identifiers") or []):
            value = identifier.get("value")
            item_path = f"$.candidates[{ci}].identifiers[{ii}]"
            if not isinstance(value, str) or not value:
                continue
            if value in within:
                issues.append(
                    EvidenceIssue(item_path, DUPLICATE_IDENTIFIER_WITHIN_CANDIDATE, f"identifier {value!r} repeats identifiers[{within[value]}] of the same candidate")
                )
            within.setdefault(value, ii)
            if value in first_owner and first_owner[value] != ci:
                issues.append(
                    EvidenceIssue(item_path, DUPLICATE_IDENTIFIER_ACROSS_CANDIDATES, f"identifier {value!r} is also submitted for candidates[{first_owner[value]}]")
                )
            first_owner.setdefault(value, ci)
            verbatim_ok = False
            for ref in identifier.get("source_refs") or []:
                ref_path = ref.get("path")
                start, end = ref.get("start_line"), ref.get("end_line")
                if ref_path not in original_texts or not isinstance(start, int) or not isinstance(end, int) or start > end:
                    continue
                try:
                    resolved = resolve_source_range(original_texts, ref_path, start, end)
                except IndexError:
                    continue
                if value in resolved:
                    verbatim_ok = True
                    break
            if not verbatim_ok:
                issues.append(
                    EvidenceIssue(item_path, IDENTIFIER_NOT_VERBATIM, f"identifier {value!r} does not occur verbatim in any of its resolved source references")
                )
        seen_per_candidate.append(within)

    seen_values = set(first_owner)
    for gi, group in enumerate(payload.get("range_groups") or []):
        notation = group.get("range_notation")
        group_path = f"$.range_groups[{gi}].range_notation"
        if not isinstance(notation, str) or not notation.strip():
            continue
        expansion = expand_range_notation(notation)
        if expansion.error:
            issues.append(
                EvidenceIssue(
                    group_path,
                    RANGE_NOTATION_UNPARSEABLE,
                    f"range notation {notation!r} is not expandable: {expansion.error}",
                )
            )
            continue
        verbatim_ok = False
        for ref in group.get("source_refs") or []:
            ref_path = ref.get("path")
            start, end = ref.get("start_line"), ref.get("end_line")
            if ref_path not in original_texts or not isinstance(start, int) or not isinstance(end, int) or start > end:
                continue
            try:
                resolved = resolve_source_range(original_texts, ref_path, start, end)
            except IndexError:
                continue
            if notation in resolved:
                verbatim_ok = True
                break
        if not verbatim_ok:
            issues.append(
                EvidenceIssue(
                    group_path,
                    RANGE_NOTATION_NOT_VERBATIM,
                    f"range notation {notation!r} does not occur verbatim in any of its resolved source references",
                )
            )
        for value in expansion.identifiers:
            if value in seen_values:
                issues.append(
                    EvidenceIssue(
                        group_path,
                        DUPLICATE_IDENTIFIER_ACROSS_CANDIDATES,
                        f"expanded identifier {value!r} duplicates another roster identifier",
                    )
                )
            seen_values.add(value)
    return issues


def hydrate_source_refs(
    payload: dict[str, Any],
    *,
    original_texts: dict[str, str],
    file_sha256: dict[str, str],
) -> dict[str, Any]:
    """Return a hydrated copy: every source ref gains resolved_text and source_sha256."""

    def hydrate_ref(ref: dict[str, Any]) -> dict[str, Any]:
        path = ref.get("path")
        start, end = ref.get("start_line"), ref.get("end_line")
        resolved = resolve_source_range(original_texts, path, start, end)
        return {
            "path": path,
            "start_line": start,
            "end_line": end,
            "resolved_text": resolved,
            "source_sha256": file_sha256[path],
        }

    def hydrate_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [hydrate_ref(ref) for ref in refs]

    hydrated_candidates = []
    for candidate in payload.get("candidates") or []:
        hydrated_candidates.append(
            {
                "identifiers": [
                    {"value": item["value"], "source_refs": hydrate_refs(item["source_refs"])}
                    for item in candidate.get("identifiers") or []
                ],
                "qualification": {
                    "reason": candidate["qualification"]["reason"],
                    "source_refs": hydrate_refs(candidate["qualification"]["source_refs"]),
                },
            }
        )
    hydrated_exclusions = [
        {
            "subject": item["subject"],
            "reason": item["reason"],
            "source_refs": hydrate_refs(item["source_refs"]),
        }
        for item in payload.get("reviewed_exclusions") or []
    ]
    hydrated_groups = [
        {
            "range_notation": item["range_notation"],
            "source_refs": hydrate_refs(item["source_refs"]),
            "qualification": {
                "reason": item["qualification"]["reason"],
                "source_refs": hydrate_refs(item["qualification"]["source_refs"]),
            },
        }
        for item in payload.get("range_groups") or []
    ]
    return {
        "candidates": hydrated_candidates,
        "reviewed_exclusions": hydrated_exclusions,
        "range_groups": hydrated_groups,
    }
