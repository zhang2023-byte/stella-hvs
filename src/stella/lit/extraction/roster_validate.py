"""Deterministic contribution-roster evidence validation and hydration.

The model selects evidence coordinates; code validates the coordinates and
resolves their exact text but never moves a reference, invents an anchor, or
claims to prove a scientific eligibility judgment. The semantic adequacy of
a follow_up prior-candidate anchor and the substance of analysis are prompt
concerns; deterministic code only verifies that submitted evidence exists at
valid current-paper coordinates and that identifiers occur verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SOURCE_PATH_NOT_ALLOWED = "source_path_not_allowed"
SOURCE_LINE_RANGE_REVERSED = "source_line_range_reversed"
SOURCE_LINE_OUT_OF_BOUNDS = "source_line_out_of_bounds"
SOURCE_RANGE_COMMENT_ONLY = "source_range_comment_only"
IDENTIFIER_NOT_VERBATIM = "identifier_not_verbatim"
DUPLICATE_IDENTIFIER_WITHIN_CONTRIBUTION = "duplicate_identifier_within_contribution"
DUPLICATE_IDENTIFIER_ACROSS_CONTRIBUTIONS = "duplicate_identifier_across_contributions"
CONTRIBUTION_SUMMARY_REQUIRED = "contribution_summary_required"
CONTRIBUTION_EVIDENCE_REQUIRED = "contribution_evidence_required"
CONTRIBUTION_TYPE_STATUS_INCOMPATIBLE = "contribution_type_status_incompatible"
BOUNDNESS_EVIDENCE_REQUIRED = "boundness_evidence_required"
REVIEWED_EXCLUSION_REASON_REQUIRED = "reviewed_exclusion_reason_required"
REVIEWED_EXCLUSION_EVIDENCE_REQUIRED = "reviewed_exclusion_evidence_required"

CANDIDATES_FOUND_FORBIDDEN_STATUSES = ("bound", "not_assessed")
ASSESSED_STATUSES = ("unbound", "possibly_unbound", "bound", "no_overall_conclusion")


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
    """Yield (json_path, ref) for every model-submitted source ref."""

    for ci, contribution in enumerate(payload.get("object_contributions") or []):
        for ii, identifier in enumerate(contribution.get("identifiers") or []):
            for ri, ref in enumerate(identifier.get("source_refs") or []):
                yield f"$.object_contributions[{ci}].identifiers[{ii}].source_refs[{ri}]", ref
        for ri, ref in enumerate(contribution.get("contribution_evidence") or []):
            yield f"$.object_contributions[{ci}].contribution_evidence[{ri}]", ref
        boundness = contribution.get("paper_boundness") or {}
        for ri, ref in enumerate(boundness.get("evidence") or []):
            yield f"$.object_contributions[{ci}].paper_boundness.evidence[{ri}]", ref
    for ei, exclusion in enumerate(payload.get("reviewed_exclusions") or []):
        for ri, ref in enumerate(exclusion.get("source_refs") or []):
            yield f"$.reviewed_exclusions[{ei}].source_refs[{ri}]", ref


def _check_coordinates(
    issues: list[EvidenceIssue],
    refs: list[dict[str, Any]],
    *,
    file_line_counts: dict[str, int],
    cleaned_texts: dict[str, str],
    base_path: str,
) -> None:
    """Check one ref (or ref list) whose JSON path is already element-exact."""

    for ri, ref in enumerate(refs):
        path = base_path
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
            issues.append(EvidenceIssue(path, SOURCE_LINE_RANGE_REVERSED, f"start_line {start} exceeds end_line {end}"))
            continue
        line_count = file_line_counts[file_path]
        if start < 1 or end > line_count:
            issues.append(EvidenceIssue(path, SOURCE_LINE_OUT_OF_BOUNDS, f"range {start}-{end} is outside {file_path} (1-{line_count})"))
            continue
        cleaned_lines = _file_lines(cleaned_texts, file_path)
        if all(not line.strip() for line in cleaned_lines[start - 1 : end]):
            issues.append(EvidenceIssue(path, SOURCE_RANGE_COMMENT_ONLY, f"range {start}-{end} in {file_path} points only to content removed from the model-facing view"))


def _occurs_verbatim(value: str, refs: list[dict[str, Any]], original_texts: dict[str, str]) -> bool:
    for ref in refs or []:
        ref_path = ref.get("path")
        start, end = ref.get("start_line"), ref.get("end_line")
        if ref_path not in original_texts or not isinstance(start, int) or not isinstance(end, int) or start > end:
            continue
        try:
            resolved = resolve_source_range(original_texts, ref_path, start, end)
        except IndexError:
            continue
        if value in resolved:
            return True
    return False


def _check_contribution(
    issues: list[EvidenceIssue],
    contribution: dict[str, Any],
    base: str,
    *,
    ci: int | None,
    first_owner: dict[str, int],
    file_line_counts: dict[str, int],
    original_texts: dict[str, str],
    cleaned_texts: dict[str, str],
) -> None:
    summary = contribution.get("contribution_summary")
    if not isinstance(summary, str) or not summary.strip():
        issues.append(EvidenceIssue(f"{base}.contribution_summary", CONTRIBUTION_SUMMARY_REQUIRED, "contribution_summary is required"))
    evidence = contribution.get("contribution_evidence") or []
    if not evidence:
        issues.append(EvidenceIssue(f"{base}.contribution_evidence", CONTRIBUTION_EVIDENCE_REQUIRED, "at least one current-paper evidence locator is required"))
    for ri, ref in enumerate(evidence):
        _check_coordinates(
            issues,
            [ref],
            file_line_counts=file_line_counts,
            cleaned_texts=cleaned_texts,
            base_path=f"{base}.contribution_evidence[{ri}]",
        )

    contribution_type = contribution.get("contribution_type")
    boundness = contribution.get("paper_boundness") or {}
    status = boundness.get("status")
    if contribution_type == "candidates_found" and status in CANDIDATES_FOUND_FORBIDDEN_STATUSES:
        issues.append(
            EvidenceIssue(
                f"{base}.paper_boundness.status",
                CONTRIBUTION_TYPE_STATUS_INCOMPATIBLE,
                f"candidates_found cannot use paper_boundness {status!r}",
            )
        )
    boundness_evidence = boundness.get("evidence") or []
    if status in ASSESSED_STATUSES and not boundness_evidence:
        issues.append(
            EvidenceIssue(
                f"{base}.paper_boundness.evidence",
                BOUNDNESS_EVIDENCE_REQUIRED,
                f"paper_boundness {status!r} requires at least one evidence locator",
            )
        )
    for ri, ref in enumerate(boundness_evidence):
        _check_coordinates(
            issues,
            [ref],
            file_line_counts=file_line_counts,
            cleaned_texts=cleaned_texts,
            base_path=f"{base}.paper_boundness.evidence[{ri}]",
        )

    within: dict[str, int] = {}
    for ii, identifier in enumerate(contribution.get("identifiers") or []):
        value = identifier.get("value")
        item_path = f"{base}.identifiers[{ii}]"
        if not isinstance(value, str) or not value:
            continue
        # The canonical contract rejects case-insensitive identifier
        # duplicates within one contribution; the submission check must
        # use the same normalization so the correction loop can fix them.
        normalized = value.strip().casefold()
        if normalized in within:
            issues.append(
                EvidenceIssue(item_path, DUPLICATE_IDENTIFIER_WITHIN_CONTRIBUTION, f"identifier {value!r} case-insensitively repeats identifiers[{within[normalized]}] of the same contribution")
            )
        within.setdefault(normalized, ii)
        if ci is not None:
            if value in first_owner and first_owner[value] != ci:
                issues.append(
                    EvidenceIssue(item_path, DUPLICATE_IDENTIFIER_ACROSS_CONTRIBUTIONS, f"identifier {value!r} is also submitted for object_contributions[{first_owner[value]}]")
                )
            first_owner.setdefault(value, ci)
        refs = identifier.get("source_refs") or []
        for ri, ref in enumerate(refs):
            _check_coordinates(
                issues,
                [ref],
                file_line_counts=file_line_counts,
                cleaned_texts=cleaned_texts,
                base_path=f"{item_path}.source_refs[{ri}]",
            )
        if not _occurs_verbatim(value, refs, original_texts):
            issues.append(
                EvidenceIssue(item_path, IDENTIFIER_NOT_VERBATIM, f"identifier {value!r} does not occur verbatim in any of its resolved source references")
            )


def validate_contribution_roster_submission(
    payload: dict[str, Any],
    *,
    file_line_counts: dict[str, int],
    original_texts: dict[str, str],
    cleaned_texts: dict[str, str],
) -> list[EvidenceIssue]:
    """Run every deterministic source-coordinate, identity, and rule check."""

    issues: list[EvidenceIssue] = []
    for path, ref in _iter_source_refs(payload):
        _check_coordinates(
            issues,
            [ref],
            file_line_counts=file_line_counts,
            cleaned_texts=cleaned_texts,
            base_path=path,
        )

    first_owner: dict[str, int] = {}
    for ci, contribution in enumerate(payload.get("object_contributions") or []):
        _check_contribution(
            issues,
            contribution,
            f"$.object_contributions[{ci}]",
            ci=ci,
            first_owner=first_owner,
            file_line_counts=file_line_counts,
            original_texts=original_texts,
            cleaned_texts=cleaned_texts,
        )

    for ei, exclusion in enumerate(payload.get("reviewed_exclusions") or []):
        reason = exclusion.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            issues.append(
                EvidenceIssue(
                    f"$.reviewed_exclusions[{ei}].reason",
                    REVIEWED_EXCLUSION_REASON_REQUIRED,
                    "reviewed exclusion reason is required",
                )
            )
        if not (exclusion.get("source_refs") or []):
            issues.append(
                EvidenceIssue(
                    f"$.reviewed_exclusions[{ei}].source_refs",
                    REVIEWED_EXCLUSION_EVIDENCE_REQUIRED,
                    "reviewed exclusion requires at least one current-paper evidence locator",
                )
            )
    return issues


def hydrate_contribution_source_refs(
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

    def hydrate_refs(refs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return [hydrate_ref(ref) for ref in refs or []]

    def hydrate_contribution(contribution: dict[str, Any]) -> dict[str, Any]:
        return {
            "identifiers": [
                {"value": item["value"], "source_refs": hydrate_refs(item.get("source_refs"))}
                for item in contribution.get("identifiers") or []
            ],
            "contribution_type": contribution["contribution_type"],
            "contribution_summary": contribution["contribution_summary"],
            "contribution_evidence": hydrate_refs(contribution.get("contribution_evidence")),
            "paper_boundness": {
                "status": (contribution.get("paper_boundness") or {}).get("status"),
                "evidence": hydrate_refs((contribution.get("paper_boundness") or {}).get("evidence")),
            },
        }

    return {
        "object_contributions": [
            hydrate_contribution(item) for item in payload.get("object_contributions") or []
        ],
        "reviewed_exclusions": [
            {
                "reason": item["reason"],
                "source_refs": hydrate_refs(item.get("source_refs")),
            }
            for item in payload.get("reviewed_exclusions") or []
        ],
    }
