#!/usr/bin/env python3
"""Build the expert-vs-AI benchmark comparison page.

This post-gold diagnostic reads expert annotations from the external private
gold store (STELLA_GOLD_DIR) plus existing AI extraction artifacts, then
writes static HTML next to the gold store (default: its sibling comparison/
directory, inside the private repository). The generated pages embed gold
values and must never be committed to the public toolchain repository. The
script never writes the gold store itself or benchmark/runs/.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "benchmark" / "runs"
LITERATURE_DIR = ROOT / "literature"
MANIFEST_PATH = ROOT / "benchmark" / "manifest" / "sampling_manifest.json"
GOLD_DIR_ENV = "STELLA_GOLD_DIR"

SCORED_FIELDS = {
    "observed_phase_space.ra",
    "observed_phase_space.dec",
    "observed_phase_space.distance",
    "observed_phase_space.parallax",
    "observed_phase_space.proper_motion_ra",
    "observed_phase_space.proper_motion_dec",
    "observed_phase_space.radial_velocity",
    "derived_kinematics.galactocentric_x",
    "derived_kinematics.galactocentric_y",
    "derived_kinematics.galactocentric_z",
    "derived_kinematics.galactocentric_radius",
    "derived_kinematics.galactocentric_vx",
    "derived_kinematics.galactocentric_vy",
    "derived_kinematics.galactocentric_vz",
    "derived_kinematics.tangential_velocity",
    "derived_kinematics.galactocentric_tangential_velocity",
    "derived_kinematics.galactic_rest_frame_velocity",
    "bound_assessment.escape_velocity",
    "bound_assessment.escape_velocity_ratio",
    "bound_assessment.escape_margin",
    "bound_assessment.bound_probability",
    "bound_assessment.unbound_probability",
    "bound_assessment.bound_status_metric",
}

DASH_TRANSLATION = str.maketrans(
    {
        "\u2212": "-",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\ufe63": "-",
        "\uff0d": "-",
    }
)
GAIA_RE = re.compile(r"(?:GAIA\s+)?(?:(E?DR[0-9])\s+)?([0-9]{12,})", re.I)
PROBABILITY_FIELDS = {
    "bound_assessment.bound_probability",
    "bound_assessment.unbound_probability",
}
ORIGIN_EQUIVALENCE = {
    "cited_from_literature": "previous_literature",
    "introduced_by_previous_paper": "previous_literature",
    "previous_literature": "previous_literature",
    "introduced_by_this_paper": "introduced_by_this_paper",
    "new_candidate": "introduced_by_this_paper",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def repo_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def normalize_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\s\-_]+", "", value.translate(DASH_TRANSLATION).strip().upper())


def parse_gaia(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, str):
        return None
    match = GAIA_RE.search(value.translate(DASH_TRANSLATION).upper())
    if not match:
        return None
    return (match.group(1) or "", match.group(2))


def text_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).translate(DASH_TRANSLATION).strip()


def display_list(values: list[str]) -> str:
    return ", ".join(value for value in values if value) or "无"


def unique_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = text_value(value)
        key = normalize_name(text) or text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def comparison_row(
    candidate: str,
    surface: str,
    field: str,
    gold: str,
    ai: str,
    status: str,
    kind: str,
    klass: str,
    *,
    review_required: bool,
    note: str = "",
) -> dict[str, Any]:
    return {
        "candidate": candidate,
        "surface": surface,
        "field": field,
        "gold": gold,
        "ai": ai,
        "status": status,
        "kind": kind,
        "class": klass,
        "review_required": review_required,
        "note": note,
    }


def status_row(gold_status: Any, ai_status: Any, *, status_match: bool) -> dict[str, Any]:
    if status_match:
        return comparison_row(
            "paper",
            "paper",
            "status",
            text_value(gold_status),
            text_value(ai_status),
            "一致",
            "aligned",
            "good",
            review_required=False,
        )
    return comparison_row(
        "paper",
        "paper",
        "status",
        text_value(gold_status),
        text_value(ai_status),
        "状态不一致",
        "status_mismatch",
        "bad",
        review_required=True,
    )


def display_gold_candidate(candidate: dict[str, Any]) -> str:
    return (
        candidate.get("paper_candidate_id")
        or candidate.get("gaia_source_id")
        or next(iter(candidate.get("aliases") or []), "")
        or "(unnamed gold candidate)"
    )


def ai_identity_values(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    identifiers = candidate.get("identifiers") or {}
    identity = candidate.get("identity") or {}
    for mapping in (identifiers, identity):
        for key in ("paper_candidate_id", "gaia_source_id", "name"):
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)
        aliases = mapping.get("aliases")
        if isinstance(aliases, list):
            values.extend(str(item) for item in aliases if str(item).strip())
    for entry in identifiers.get("all") or []:
        if isinstance(entry, dict) and entry.get("value"):
            values.append(str(entry["value"]))
    for key in ("record_id", "id", "name"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    return values


def display_ai_candidate(candidate: dict[str, Any], index: int) -> str:
    return next(iter(ai_identity_values(candidate)), "") or f"AI candidate {index + 1}"


def ai_primary_identifier(candidate: dict[str, Any], key: str) -> str:
    identifiers = candidate.get("identifiers") or {}
    identity = candidate.get("identity") or {}
    for mapping in (identifiers, identity):
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def identity_name_values(candidate: dict[str, Any]) -> list[str]:
    return unique_values(
        [
            value
            for value in ai_identity_values(candidate)
            if not parse_gaia(value)
        ]
    )


def identity_gaia_values(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    primary = ai_primary_identifier(candidate, "gaia_source_id")
    if primary:
        values.append(primary)
    values.extend(value for value in ai_identity_values(candidate) if parse_gaia(value))
    return unique_values(values)


def name_in_values(value: str, values: list[str]) -> str:
    wanted = normalize_name(value)
    if not wanted:
        return ""
    for candidate in values:
        if normalize_name(candidate) == wanted:
            return candidate
    return ""


def identity_record(values: list[str]) -> dict[str, Any]:
    return {
        "names": {normalize_name(value) for value in values if normalize_name(value) and not parse_gaia(value)},
        "gaias": [gaia for gaia in (parse_gaia(value) for value in values) if gaia],
    }


def gold_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    values = [
        candidate.get("paper_candidate_id", ""),
        candidate.get("gaia_source_id", ""),
        *(candidate.get("aliases") or []),
    ]
    return identity_record([str(value) for value in values if str(value).strip()])


def ai_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    return identity_record(ai_identity_values(candidate))


def gaia_compatible(left: tuple[str, str], right: tuple[str, str]) -> bool:
    return left[1] == right[1] and (not left[0] or not right[0] or left[0] == right[0])


def canonical_origin(value: Any) -> str:
    text = text_value(value)
    return ORIGIN_EQUIVALENCE.get(text, text)


def source_ref_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def candidate_evidence_count(candidate: dict[str, Any], *, source: str) -> int:
    if source == "gold":
        return source_ref_count(candidate.get("evidence"))
    inclusion = candidate.get("inclusion_assessment") or {}
    candidate_origin = candidate.get("candidate_origin") or {}
    return source_ref_count(inclusion.get("source_refs")) + source_ref_count(
        candidate_origin.get("source_refs")
    )


def quantity_evidence_count(quantity: dict[str, Any], *, source: str) -> int:
    key = "evidence" if source == "gold" else "source_refs"
    return source_ref_count(quantity.get(key))


def match_candidates(gold_candidates: list[dict[str, Any]], ai_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    gold_ids = [gold_identity(candidate) for candidate in gold_candidates]
    ai_ids = [ai_identity(candidate) for candidate in ai_candidates]
    unmatched_gold = set(range(len(gold_candidates)))
    unmatched_ai = set(range(len(ai_candidates)))
    pairs: list[dict[str, Any]] = []

    def take(gold_index: int, ai_index: int, method: str, detail: str) -> None:
        unmatched_gold.discard(gold_index)
        unmatched_ai.discard(ai_index)
        pairs.append(
            {
                "gold_index": gold_index,
                "ai_index": ai_index,
                "gold_id": display_gold_candidate(gold_candidates[gold_index]),
                "ai_id": display_ai_candidate(ai_candidates[ai_index], ai_index),
                "method": method,
                "detail": detail,
            }
        )

    for gold_index in list(sorted(unmatched_gold)):
        for ai_index in list(sorted(unmatched_ai)):
            for gold_gaia in gold_ids[gold_index]["gaias"]:
                for ai_gaia in ai_ids[ai_index]["gaias"]:
                    if gaia_compatible(gold_gaia, ai_gaia):
                        take(gold_index, ai_index, "gaia_id", gold_gaia[1])
                        break
                if gold_index not in unmatched_gold:
                    break
            if gold_index not in unmatched_gold:
                break

    for gold_index in list(sorted(unmatched_gold)):
        for ai_index in list(sorted(unmatched_ai)):
            shared = gold_ids[gold_index]["names"] & ai_ids[ai_index]["names"]
            if shared:
                take(gold_index, ai_index, "alias", sorted(shared)[0])
                break

    return {
        "pairs": pairs,
        "unmatched_gold": [
            {"index": index, "display_id": display_gold_candidate(gold_candidates[index])}
            for index in sorted(unmatched_gold)
        ],
        "unmatched_ai": [
            {"index": index, "display_id": display_ai_candidate(ai_candidates[index], index)}
            for index in sorted(unmatched_ai)
        ],
    }


def quantity_has_value(quantity: Any) -> bool:
    if not isinstance(quantity, dict):
        return False
    for key in ("value", "raw_value", "range_lower", "range_upper"):
        value = quantity.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def parse_number(value: Any) -> float | None:
    text = text_value(value)
    if not text or ":" in text:
        return None
    text = (
        text.replace(",", "")
        .replace("~", "")
        .replace("≈", "")
        .replace("∼", "")
        .replace("%", "")
    )
    match = re.search(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def normalize_scalar(field: str, value: Any, unit: Any = "") -> tuple[str, float | str]:
    number = parse_number(value)
    unit_text = text_value(unit)
    if number is not None:
        if field in PROBABILITY_FIELDS and ("%" in unit_text or abs(number) > 1):
            number /= 100.0
        return ("number", number)
    text = re.sub(r"[\s+~≈∼]+", "", text_value(value).casefold())
    return ("text", text)


def scalar_equal(field: str, left: Any, right: Any, *, left_unit: Any = "", right_unit: Any = "") -> bool:
    left_kind, left_value = normalize_scalar(field, left, left_unit)
    right_kind, right_value = normalize_scalar(field, right, right_unit)
    if left_kind == right_kind == "number":
        left_float = float(left_value)
        right_float = float(right_value)
        return abs(left_float - right_float) <= max(1e-9, 1e-6 * max(abs(left_float), abs(right_float), 1.0))
    return left_value == right_value


def canonical_unit(value: Any) -> str:
    text = text_value(value).casefold()
    if ";" in text:
        text = text.split(";", 1)[0]
    text = text.replace("−", "-")
    text = text.replace("yr^-1", "/yr")
    text = text.replace("yr^{-1}", "/yr")
    text = text.replace("s^-1", "/s")
    text = text.replace("s^{-1}", "/s")
    text = text.replace("year", "yr")
    text = re.sub(r"\s+", "", text)
    text = text.replace("kms", "km/s") if text == "kms" else text
    aliases = {
        "kms-1": "km/s",
        "kms^-1": "km/s",
        "km/s": "km/s",
        "kms^{-1}": "km/s",
        "masyr-1": "mas/yr",
        "masyr^-1": "mas/yr",
        "mas/yr": "mas/yr",
        "masyr^{-1}": "mas/yr",
        "kms^-2": "km/s^2",
        "kms-2": "km/s^2",
    }
    return aliases.get(text, text)


def units_equivalent(field: str, gold_unit: Any, ai_unit: Any) -> bool:
    left = canonical_unit(gold_unit)
    right = canonical_unit(ai_unit)
    if left == right:
        return True
    if field in PROBABILITY_FIELDS and {left, right} <= {"", "%"}:
        return True
    return False


def structured_uncertainty(quantity: dict[str, Any]) -> dict[str, str]:
    return {
        key: text_value(quantity.get(key))
        for key in ("error", "lower_error", "upper_error")
        if text_value(quantity.get(key))
    }


def raw_mentions_uncertainty(quantity: dict[str, Any]) -> bool:
    raw = text_value(quantity.get("raw_value"))
    return any(marker in raw for marker in ("±", "+/-", "_-", "^+", "-/+", "+-"))


def limit_kind(quantity: dict[str, Any]) -> str:
    return text_value(quantity.get("limit_kind")) or "measurement"


def limit_values(quantity: dict[str, Any]) -> tuple[str, str]:
    return (text_value(quantity.get("range_lower")), text_value(quantity.get("range_upper")))


def flatten_gold_quantities(candidate: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fields: dict[str, list[dict[str, Any]]] = {}
    for quantity in candidate.get("quantities") or []:
        field = quantity.get("field")
        if field in SCORED_FIELDS:
            fields.setdefault(field, []).append(quantity)
    return fields


def flatten_ai_quantities(candidate: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fields: dict[str, list[dict[str, Any]]] = {}
    core = candidate.get("core") or {}
    for group in ("observed_phase_space", "derived_kinematics", "bound_assessment"):
        values = core.get(group) or {}
        if not isinstance(values, dict):
            continue
        for name, record in values.items():
            if isinstance(record, dict) and quantity_has_value(record):
                field = f"{group}.{name}"
                fields.setdefault(field, []).append(record)
    return fields


def quantity_value(quantity: dict[str, Any]) -> str:
    if quantity.get("limit_kind") == "range":
        value = f"{quantity.get('range_lower', '')} to {quantity.get('range_upper', '')}".strip()
    else:
        value = str(quantity.get("value") or "").strip()
    error = str(quantity.get("error") or "").strip()
    lower = str(quantity.get("lower_error") or "").strip()
    upper = str(quantity.get("upper_error") or "").strip()
    unit = str(quantity.get("unit") or "").strip()
    parts = [value] if value else []
    if error:
        parts.append(f"+/- {error}")
    elif lower or upper:
        parts.append(f"-{lower or '?'} +{upper or '?'}")
    if unit:
        parts.append(unit)
    return " ".join(parts) if parts else "(empty)"


def compare_identity_rows(
    gold_candidate: dict[str, Any],
    ai_candidate: dict[str, Any],
    candidate_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    ai_names = identity_name_values(ai_candidate)
    ai_gaias = identity_gaia_values(ai_candidate)

    gold_paper_id = text_value(gold_candidate.get("paper_candidate_id"))
    ai_paper_id = ai_primary_identifier(ai_candidate, "paper_candidate_id")
    gold_gaia = text_value(gold_candidate.get("gaia_source_id"))
    gold_gaia_parsed = parse_gaia(gold_gaia)
    ai_paper_gaia = parse_gaia(ai_paper_id)
    if not gold_paper_id and not ai_paper_id:
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "paper_candidate_id",
                "无",
                "无",
                "一致",
                "aligned",
                "good",
                review_required=False,
            )
        )
    elif (
        not gold_paper_id
        and gold_gaia_parsed
        and ai_paper_gaia
        and gaia_compatible(gold_gaia_parsed, ai_paper_gaia)
    ):
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "paper_candidate_id",
                "Gold 未单列",
                ai_paper_id,
                "一致",
                "aligned",
                "good",
                review_required=False,
                note="AI paper_candidate_id 使用同一个 Gaia source id；gold 只在 gaia_source_id 记录。",
            )
        )
    elif not gold_paper_id and ai_paper_id:
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "paper_candidate_id",
                "Gold 未单列",
                ai_paper_id,
                "AI-only",
                "identity_ai_only",
                "bad",
                review_required=True,
            )
        )
    elif gold_paper_id and name_in_values(gold_paper_id, [ai_paper_id, *ai_names]):
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "paper_candidate_id",
                gold_paper_id,
                ai_paper_id or name_in_values(gold_paper_id, ai_names),
                "一致",
                "aligned",
                "good",
                review_required=False,
            )
        )
    else:
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "paper_candidate_id",
                gold_paper_id or "无",
                ai_paper_id or "未提取",
                "身份不一致",
                "identity_mismatch",
                "critical",
                review_required=True,
            )
        )

    ai_gaia_display = next(iter(ai_gaias), "")
    ai_gaia_parsed = parse_gaia(ai_gaia_display)
    if not gold_gaia and not ai_gaia_display:
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "gaia_source_id",
                "无",
                "无",
                "一致",
                "aligned",
                "good",
                review_required=False,
            )
        )
    elif not gold_gaia and ai_gaia_display:
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "gaia_source_id",
                "Gold 未记录",
                ai_gaia_display,
                "AI-only",
                "identity_ai_only",
                "bad",
                review_required=True,
                note="AI 提取了 Gaia source id，但 gold 未记录。",
            )
        )
    elif gold_gaia and not ai_gaia_display:
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "gaia_source_id",
                gold_gaia,
                "未提取",
                "AI 缺失",
                "identity_missing",
                "bad",
                review_required=True,
            )
        )
    elif gold_gaia_parsed and ai_gaia_parsed and gaia_compatible(gold_gaia_parsed, ai_gaia_parsed):
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "gaia_source_id",
                gold_gaia,
                ai_gaia_display,
                "一致",
                "aligned",
                "good",
                review_required=False,
                note="source_id 数字一致。" if gold_gaia != ai_gaia_display else "",
            )
        )
    elif gold_gaia_parsed and ai_gaia_parsed and gold_gaia_parsed[1] == ai_gaia_parsed[1]:
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "gaia_source_id",
                gold_gaia,
                ai_gaia_display,
                "Gaia release差异",
                "identity_release_mismatch",
                "warn",
                review_required=True,
            )
        )
    else:
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "gaia_source_id",
                gold_gaia,
                ai_gaia_display or "未提取",
                "Gaia source_id不一致",
                "identity_mismatch",
                "critical",
                review_required=True,
            )
        )

    gold_aliases = unique_values([str(value) for value in gold_candidate.get("aliases") or []])
    gold_known = [gold_paper_id, gold_gaia, *gold_aliases]
    ai_aliases = [
        value
        for value in ai_names
        if not name_in_values(value, [gold_paper_id, *gold_aliases])
    ]
    missing_aliases = [alias for alias in gold_aliases if not name_in_values(alias, ai_names)]
    extra_aliases = [
        alias
        for alias in ai_aliases
        if not any(normalize_name(alias) == normalize_name(known) for known in gold_known if known)
    ]
    if not missing_aliases and not extra_aliases:
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "aliases",
                display_list(gold_aliases),
                display_list(gold_aliases or extra_aliases),
                "一致",
                "aligned",
                "good",
                review_required=False,
            )
        )
    else:
        notes = []
        if missing_aliases:
            notes.append(f"AI 缺少 alias: {display_list(missing_aliases)}")
        if extra_aliases:
            notes.append(f"AI-only alias: {display_list(extra_aliases)}")
        rows.append(
            comparison_row(
                candidate_id,
                "identity",
                "aliases",
                display_list(gold_aliases),
                display_list(extra_aliases or ai_aliases),
                "alias差异",
                "identity_alias_mismatch",
                "bad",
                review_required=True,
                note="; ".join(notes),
            )
        )

    return rows


def compare_origin_and_evidence_rows(
    gold_candidate: dict[str, Any],
    ai_candidate: dict[str, Any],
    candidate_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    gold_origin = text_value(gold_candidate.get("origin_type"))
    ai_origin = text_value((ai_candidate.get("candidate_origin") or {}).get("origin_type"))
    if canonical_origin(gold_origin) == canonical_origin(ai_origin):
        rows.append(
            comparison_row(
                candidate_id,
                "origin",
                "origin_type",
                gold_origin or "无",
                ai_origin or "无",
                "一致",
                "aligned",
                "good",
                review_required=False,
                note="语义等价。" if gold_origin != ai_origin else "",
            )
        )
    else:
        rows.append(
            comparison_row(
                candidate_id,
                "origin",
                "origin_type",
                gold_origin or "无",
                ai_origin or "未提取",
                "来源分类差异",
                "origin_mismatch",
                "warn",
                review_required=True,
            )
        )

    gold_refs = candidate_evidence_count(gold_candidate, source="gold")
    ai_refs = candidate_evidence_count(ai_candidate, source="ai")
    if gold_refs and ai_refs:
        rows.append(
            comparison_row(
                candidate_id,
                "evidence",
                "candidate.evidence",
                f"{gold_refs} locator(s)",
                f"{ai_refs} source_ref(s)",
                "一致",
                "aligned",
                "good",
                review_required=False,
            )
        )
    elif gold_refs and not ai_refs:
        rows.append(
            comparison_row(
                candidate_id,
                "evidence",
                "candidate.evidence",
                f"{gold_refs} locator(s)",
                "未提取",
                "证据缺失",
                "evidence_missing",
                "warn",
                review_required=True,
            )
        )
    else:
        rows.append(
            comparison_row(
                candidate_id,
                "evidence",
                "candidate.evidence",
                "无",
                f"{ai_refs} source_ref(s)" if ai_refs else "无",
                "一致",
                "aligned",
                "good",
                review_required=False,
            )
        )
    return rows


def compare_quantity_row(
    candidate_id: str,
    field: str,
    gold_quantity: dict[str, Any],
    ai_quantity: dict[str, Any] | None,
) -> dict[str, Any]:
    gold_display = quantity_value(gold_quantity)
    if ai_quantity is None:
        return comparison_row(
            candidate_id,
            "quantity",
            field,
            gold_display,
            "未提取",
            "AI 缺失",
            "quantity_missing",
            "bad",
            review_required=True,
        )

    ai_display = quantity_value(ai_quantity)
    notes: list[str] = []
    gold_limit = limit_kind(gold_quantity)
    ai_limit = limit_kind(ai_quantity)
    value_equal = True
    if gold_limit == "range" or ai_limit == "range":
        gold_lower, gold_upper = limit_values(gold_quantity)
        ai_lower, ai_upper = limit_values(ai_quantity)
        value_equal = scalar_equal(field, gold_lower, ai_lower) and scalar_equal(field, gold_upper, ai_upper)
    else:
        value_equal = scalar_equal(
            field,
            gold_quantity.get("value"),
            ai_quantity.get("value"),
            left_unit=gold_quantity.get("unit"),
            right_unit=ai_quantity.get("unit"),
        )
    if not value_equal:
        return comparison_row(
            candidate_id,
            "quantity",
            field,
            gold_display,
            ai_display,
            "数值不一致",
            "quantity_numeric_mismatch",
            "critical",
            review_required=True,
        )

    if gold_limit != ai_limit:
        return comparison_row(
            candidate_id,
            "quantity",
            field,
            gold_display,
            ai_display,
            "范围/上限语义差异",
            "quantity_limit_mismatch",
            "warn",
            review_required=True,
        )

    gold_uncertainty = structured_uncertainty(gold_quantity)
    ai_uncertainty = structured_uncertainty(ai_quantity)
    if gold_uncertainty and not ai_uncertainty:
        if raw_mentions_uncertainty(ai_quantity):
            notes.append("AI raw_value 含误差，但 error/lower/upper 字段未结构化。")
        return comparison_row(
            candidate_id,
            "quantity",
            field,
            gold_display,
            ai_display,
            "缺误差",
            "quantity_uncertainty_missing",
            "warn",
            review_required=True,
            note=" ".join(notes),
        )
    if gold_uncertainty and ai_uncertainty:
        all_keys = set(gold_uncertainty) | set(ai_uncertainty)
        for key in all_keys:
            if not scalar_equal(field, gold_uncertainty.get(key), ai_uncertainty.get(key)):
                return comparison_row(
                    candidate_id,
                    "quantity",
                    field,
                    gold_display,
                    ai_display,
                    "误差不一致",
                    "quantity_uncertainty_mismatch",
                    "warn",
                    review_required=True,
                )
    if not gold_uncertainty and ai_uncertainty:
        return comparison_row(
            candidate_id,
            "quantity",
            field,
            gold_display,
            ai_display,
            "AI-only误差",
            "quantity_uncertainty_ai_only",
            "warn",
            review_required=True,
        )

    if not units_equivalent(field, gold_quantity.get("unit"), ai_quantity.get("unit")):
        return comparison_row(
            candidate_id,
            "quantity",
            field,
            gold_display,
            ai_display,
            "单位/格式差异",
            "quantity_unit_mismatch",
            "warn",
            review_required=True,
        )

    gold_refs = quantity_evidence_count(gold_quantity, source="gold")
    ai_refs = quantity_evidence_count(ai_quantity, source="ai")
    if gold_refs and not ai_refs:
        return comparison_row(
            candidate_id,
            "quantity",
            field,
            gold_display,
            ai_display,
            "证据缺失",
            "quantity_evidence_missing",
            "warn",
            review_required=True,
        )

    return comparison_row(
        candidate_id,
        "quantity",
        field,
        gold_display,
        ai_display,
        "一致",
        "aligned",
        "good",
        review_required=False,
    )


def compare_candidate_surface(gold_candidate: dict[str, Any], ai_candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_id = display_gold_candidate(gold_candidate)
    rows: list[dict[str, Any]] = []
    rows.extend(compare_identity_rows(gold_candidate, ai_candidate, candidate_id))
    rows.extend(compare_origin_and_evidence_rows(gold_candidate, ai_candidate, candidate_id))

    gold_fields = flatten_gold_quantities(gold_candidate)
    ai_fields = flatten_ai_quantities(ai_candidate)
    for field in sorted(gold_fields):
        gold_values = gold_fields[field]
        ai_values = ai_fields.get(field) or []
        for index, gold_quantity in enumerate(gold_values):
            ai_quantity = ai_values[index] if index < len(ai_values) else None
            rows.append(compare_quantity_row(candidate_id, field, gold_quantity, ai_quantity))

    for field, quantities in sorted(ai_fields.items()):
        extra = quantities[len(gold_fields.get(field, [])) :]
        for quantity in extra:
            rows.append(
                comparison_row(
                    candidate_id,
                    "quantity",
                    field,
                    "Gold 未记录",
                    quantity_value(quantity),
                    "AI-only",
                    "quantity_ai_only",
                    "bad",
                    review_required=True,
                )
            )

    return {"rows": rows}


def candidate_set_rows(matches: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for missing in matches["unmatched_gold"]:
        rows.append(
            comparison_row(
                missing["display_id"],
                "candidate",
                "candidate_set",
                "Gold candidate",
                "未匹配",
                "AI 缺失",
                "candidate_missing",
                "bad",
                review_required=True,
            )
        )
    for extra in matches["unmatched_ai"]:
        rows.append(
            comparison_row(
                extra["display_id"],
                "candidate",
                "candidate_set",
                "Gold 未记录",
                "AI candidate",
                "AI-only",
                "candidate_ai_only",
                "bad",
                review_required=True,
            )
        )
    return rows


def row_count(rows: list[dict[str, Any]], *, surface: str | None = None, kinds: set[str] | None = None) -> int:
    count = 0
    for row in rows:
        if surface is not None and row["surface"] != surface:
            continue
        if kinds is not None and row["kind"] not in kinds:
            continue
        count += 1
    return count


def review_row_count(rows: list[dict[str, Any]], *, surface: str | None = None, kinds: set[str] | None = None) -> int:
    return sum(
        1
        for row in rows
        if row["review_required"]
        and (surface is None or row["surface"] == surface)
        and (kinds is None or row["kind"] in kinds)
    )


def summarize_rows(rows: list[dict[str, Any]], matches: dict[str, Any], *, status_match: bool) -> dict[str, Any]:
    return {
        "gold_missing_in_ai": len(matches["unmatched_gold"]),
        "ai_extra_candidates": len(matches["unmatched_ai"]),
        "candidate_issues": review_row_count(rows, surface="candidate"),
        "identity_issues": review_row_count(rows, surface="identity"),
        "origin_issues": review_row_count(rows, surface="origin"),
        "evidence_issues": review_row_count(rows, surface="evidence")
        + review_row_count(rows, kinds={"quantity_evidence_missing"}),
        "quantity_review_items": review_row_count(rows, surface="quantity"),
        "quantity_numeric_mismatch": review_row_count(rows, kinds={"quantity_numeric_mismatch"}),
        "quantity_missing": review_row_count(rows, kinds={"quantity_missing"}),
        "quantity_uncertainty_issues": review_row_count(
            rows,
            kinds={
                "quantity_uncertainty_missing",
                "quantity_uncertainty_mismatch",
                "quantity_uncertainty_ai_only",
            },
        ),
        "quantity_unit_issues": review_row_count(rows, kinds={"quantity_unit_mismatch"}),
        "ai_only_quantities": review_row_count(rows, kinds={"quantity_ai_only"}),
        "aligned_items": row_count(rows, kinds={"aligned"}),
        "review_items": review_row_count(rows),
        "status_mismatch": 0 if status_match else 1,
    }


def load_manifest() -> dict[str, dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        return {}
    payload = read_json(MANIFEST_PATH)
    return {item.get("arxiv_id", ""): item for item in payload.get("papers") or []}


def iter_gold_sources(gold_dir: Path) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(gold_dir.glob("*/annotation_*.json")):
        payload = read_json(path)
        key = (str(payload.get("arxiv_id") or path.parent.name), str(payload.get("annotator") or ""))
        seen.add(key)
        sources.append({"path": path, "payload": payload, "kind": "final_annotation"})
    for path in sorted(gold_dir.glob("*/draft_*.json")):
        payload = read_json(path).get("payload") or {}
        key = (str(payload.get("arxiv_id") or path.parent.name), str(payload.get("annotator") or ""))
        if key in seen:
            continue
        sources.append({"path": path, "payload": payload, "kind": "draft_checkpoint"})
    return sources


def ai_sources_for(arxiv_id: str) -> list[dict[str, Any]]:
    sources = []
    for path in sorted(RUNS_DIR.glob(f"*/{arxiv_id}/literature_hvs_candidates.json")):
        run_id = path.parents[1].name
        sources.append({"label": f"benchmark run: {run_id}", "path": path})
    literature_path = LITERATURE_DIR / arxiv_id / "literature_hvs_candidates.json"
    if literature_path.exists():
        sources.append({"label": "literature current extraction", "path": literature_path})
    return sources


def build_comparison(source: dict[str, Any], manifest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    gold = source["payload"]
    arxiv_id = gold.get("arxiv_id") or source["path"].parent.name
    ai_source = next(iter(ai_sources_for(arxiv_id)), None)
    ai = read_json(ai_source["path"]) if ai_source else {}
    gold_candidates = gold.get("candidates") or []
    ai_candidates = ai.get("candidates") or []
    matches = match_candidates(gold_candidates, ai_candidates)
    matched_candidates = []
    rows: list[dict[str, Any]] = []
    rows.extend(candidate_set_rows(matches))
    for pair in matches["pairs"]:
        surface_comparison = compare_candidate_surface(
            gold_candidates[pair["gold_index"]],
            ai_candidates[pair["ai_index"]],
        )
        rows.extend(surface_comparison["rows"])
        matched_candidates.append({**pair, "surface_comparison": surface_comparison})

    ai_status = (ai.get("extraction") or {}).get("status") or ai.get("status") or "unknown"
    status_match = gold.get("status") == ai_status
    rows.append(status_row(gold.get("status"), ai_status, status_match=status_match))
    entry = manifest.get(arxiv_id, {})
    surface_summary = summarize_rows(rows, matches, status_match=status_match)
    return {
        "arxiv_id": arxiv_id,
        "title": (ai.get("paper") or {}).get("title") or "",
        "gold_path": repo_path(source["path"]),
        "gold_kind": source["kind"],
        "ai_source_label": ai_source["label"] if ai_source else "missing",
        "ai_source_path": repo_path(ai_source["path"]) if ai_source else "",
        "manifest": entry,
        "gold_status": gold.get("status"),
        "ai_status": ai_status,
        "status_match": status_match,
        "gold_notes": gold.get("notes") or "",
        "ai_summary": (ai.get("extraction") or {}).get("summary") or "",
        "ai_candidate_groups": ai.get("candidate_groups_considered") or [],
        "gold_candidates": gold_candidates,
        "ai_candidates": ai_candidates,
        "candidate_match": matches,
        "matched_candidates": matched_candidates,
        "comparison_rows": rows,
        "summary": {
            "gold_candidates": len(gold_candidates),
            "ai_candidates": len(ai_candidates),
            "matched_candidates": len(matches["pairs"]),
            **surface_summary,
        },
    }


def build_data(gold_dir: Path) -> dict[str, Any]:
    manifest = load_manifest()
    comparisons = [build_comparison(source, manifest) for source in iter_gold_sources(gold_dir)]
    comparisons.sort(key=lambda item: item["arxiv_id"])
    totals = {
        "papers": len({item["arxiv_id"] for item in comparisons}),
        "comparisons": len(comparisons),
        "gold_candidates": sum(item["summary"]["gold_candidates"] for item in comparisons),
        "ai_candidates": sum(item["summary"]["ai_candidates"] for item in comparisons),
        "matched_candidates": sum(item["summary"]["matched_candidates"] for item in comparisons),
        "gold_missing_in_ai": sum(item["summary"]["gold_missing_in_ai"] for item in comparisons),
        "ai_extra_candidates": sum(item["summary"]["ai_extra_candidates"] for item in comparisons),
        "candidate_issues": sum(item["summary"]["candidate_issues"] for item in comparisons),
        "identity_issues": sum(item["summary"]["identity_issues"] for item in comparisons),
        "origin_issues": sum(item["summary"]["origin_issues"] for item in comparisons),
        "evidence_issues": sum(item["summary"]["evidence_issues"] for item in comparisons),
        "quantity_review_items": sum(item["summary"]["quantity_review_items"] for item in comparisons),
        "quantity_numeric_mismatch": sum(item["summary"]["quantity_numeric_mismatch"] for item in comparisons),
        "quantity_missing": sum(item["summary"]["quantity_missing"] for item in comparisons),
        "quantity_uncertainty_issues": sum(item["summary"]["quantity_uncertainty_issues"] for item in comparisons),
        "quantity_unit_issues": sum(item["summary"]["quantity_unit_issues"] for item in comparisons),
        "ai_only_quantities": sum(item["summary"]["ai_only_quantities"] for item in comparisons),
        "aligned_items": sum(item["summary"]["aligned_items"] for item in comparisons),
        "review_items": sum(item["summary"]["review_items"] for item in comparisons),
        "status_mismatch": sum(item["summary"]["status_mismatch"] for item in comparisons),
    }
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "totals": totals,
        "comparisons": comparisons,
    }


def metric(label: str, value: Any, klass: str = "") -> str:
    class_name = f' class="metric {klass}"' if klass else ' class="metric"'
    return f'<div{class_name}><span>{esc(label)}</span><strong>{esc(value)}</strong></div>'


def issue_total(summary: dict[str, Any]) -> int:
    return int(summary["review_items"])


def verdict(summary: dict[str, Any]) -> tuple[str, str]:
    return ("clean", "Aligned") if issue_total(summary) == 0 else ("review", "Review")


def one_line_finding(item: dict[str, Any]) -> str:
    summary = item["summary"]
    if issue_total(summary) == 0:
        return "Expert and AI agree across identity and scored quantities."
    parts = []
    if summary["status_mismatch"]:
        parts.append("status differs")
    if summary["candidate_issues"]:
        parts.append(f"{summary['candidate_issues']} candidate issue{'s' if summary['candidate_issues'] != 1 else ''}")
    if summary["identity_issues"]:
        parts.append(f"{summary['identity_issues']} identity issue{'s' if summary['identity_issues'] != 1 else ''}")
    if summary["quantity_numeric_mismatch"]:
        parts.append(f"{summary['quantity_numeric_mismatch']} numeric mismatch{'es' if summary['quantity_numeric_mismatch'] != 1 else ''}")
    if summary["quantity_missing"]:
        parts.append(f"{summary['quantity_missing']} missing quantity value{'s' if summary['quantity_missing'] != 1 else ''}")
    other_quantity = (
        summary["quantity_uncertainty_issues"]
        + summary["quantity_unit_issues"]
        + summary["ai_only_quantities"]
    )
    if other_quantity:
        parts.append(f"{other_quantity} quantity review item{'s' if other_quantity != 1 else ''}")
    if summary["origin_issues"] or summary["evidence_issues"]:
        parts.append(f"{summary['origin_issues'] + summary['evidence_issues']} provenance/evidence issue{'s' if summary['origin_issues'] + summary['evidence_issues'] != 1 else ''}")
    return "; ".join(parts) + "."


def stat_cell(label: str, value: Any, bad: bool = False) -> str:
    klass = " bad" if bad else ""
    return f'<span class="stat{klass}"><b>{esc(value)}</b><small>{esc(label)}</small></span>'


def render_index_html(data: dict[str, Any]) -> str:
    cards = []
    for item in data["comparisons"]:
        summary = item["summary"]
        verdict_class, verdict_text = verdict(summary)
        stats = "".join(
            [
                stat_cell("Gold", summary["gold_candidates"]),
                stat_cell("AI", summary["ai_candidates"]),
                stat_cell("Matched", summary["matched_candidates"]),
                stat_cell("Candidate", summary["candidate_issues"], summary["candidate_issues"] > 0),
                stat_cell("Identity", summary["identity_issues"], summary["identity_issues"] > 0),
                stat_cell("Quantity", summary["quantity_review_items"], summary["quantity_review_items"] > 0),
            ]
        )
        role = item["manifest"].get("role", "")
        stratum = item["manifest"].get("stratum", "")
        cards.append(
            f'<a class="paper-row {verdict_class}" data-state="{verdict_class}" href="{esc(item["detail_href"])}">'
            f'<span class="verdict">{esc(verdict_text)}</span>'
            f'<span class="paper-main"><span class="eyebrow">{esc(role)} / {esc(stratum)}</span>'
            f'<strong>{esc(item["arxiv_id"])}</strong><em>{esc(item["title"])}</em>'
            f'<span class="finding">{esc(one_line_finding(item))}</span></span>'
            f'<span class="stat-strip">{stats}</span></a>'
        )
    clean_count = sum(1 for item in data["comparisons"] if issue_total(item["summary"]) == 0)
    review_count = len(data["comparisons"]) - clean_count
    return PAGE_TEMPLATE.format(
        title="Gold vs AI Comparison",
        body=f"""
        <section class="hero">
          <p class="eyebrow">POST-GOLD DIAGNOSTIC</p>
          <h1>Gold vs AI</h1>
          <div class="hero-metrics">
            {metric("Papers", data["totals"]["papers"])}
            {metric("Aligned", clean_count, "good" if clean_count else "")}
            {metric("Review", review_count, "strong" if review_count else "")}
            {metric("Candidate issues", data["totals"]["candidate_issues"], "strong" if data["totals"]["candidate_issues"] else "")}
            {metric("Identity issues", data["totals"]["identity_issues"], "strong" if data["totals"]["identity_issues"] else "")}
            {metric("Numeric diffs", data["totals"]["quantity_numeric_mismatch"], "strong" if data["totals"]["quantity_numeric_mismatch"] else "")}
          </div>
        </section>
        <section class="toolbar" aria-label="Paper filters">
          <button class="filter active" type="button" data-filter="all">All</button>
          <button class="filter" type="button" data-filter="review">Review</button>
          <button class="filter" type="button" data-filter="clean">Aligned</button>
          <span>Generated {esc(data["generated_at"])}</span>
        </section>
        <section class="paper-list">{''.join(cards)}</section>
        """,
    )


def comparison_table(rows: list[dict[str, Any]], empty: str) -> str:
    body_rows = []
    for row in rows:
        note = f'<div class="note">{esc(row["note"])}</div>' if row.get("note") else ""
        body_rows.append(
            f"<tr class=\"row-{esc(row['class'])}\">"
            f"<td>{esc(row['candidate'])}</td>"
            f"<td>{esc(row['surface'])}</td>"
            f"<td class=\"field\">{esc(row['field'])}</td>"
            f"<td>{esc(row['gold'])}</td>"
            f"<td>{esc(row['ai'])}</td>"
            f"<td><span class=\"badge {esc(row['class'])}\">{esc(row['status'])}</span>{note}</td>"
            "</tr>"
        )
    if not body_rows:
        body_rows.append(f'<tr><td colspan="6">{esc(empty)}</td></tr>')
    return (
        '<table class="issue-table"><thead><tr>'
        "<th>候选</th><th>层级</th><th>字段</th><th>专家 gold</th><th>AI</th><th>判定</th>"
        f"</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
    )


def details_block(title: str, summary: str, body: str, *, open_by_default: bool = False) -> str:
    open_attr = " open" if open_by_default else ""
    return f"""
    <details class="fold"{open_attr}>
      <summary><span>{esc(title)}</span><b>{esc(summary)}</b></summary>
      <div class="fold-body">{body}</div>
    </details>
    """


def render_detail_html(item: dict[str, Any]) -> str:
    summary = item["summary"]
    verdict_class, verdict_text = verdict(summary)
    matched = "".join(
        f"<li>{esc(match['gold_id'])} ↔ {esc(match['ai_id'])} <span class=\"muted\">({esc(match['method'])}: {esc(match['detail'])})</span></li>"
        for match in item["matched_candidates"]
    ) or "<li>无匹配候选。</li>"
    ai_groups = "".join(
        f"<li><code>{esc(group.get('group_id', ''))}</code>: <strong>{esc(group.get('decision', ''))}</strong>. {esc(group.get('reason', ''))}</li>"
        for group in item["ai_candidate_groups"]
    ) or "<li>AI 未记录 candidate_groups_considered。</li>"
    issue_count = issue_total(summary)
    review_rows = [row for row in item["comparison_rows"] if row["review_required"]]
    aligned_rows = [row for row in item["comparison_rows"] if not row["review_required"]]
    issue_table = comparison_table(review_rows, "无需要复核的差异。")
    aligned_table = comparison_table(aligned_rows, "无一致项。")
    body = f"""
    <section class="detail-hero {verdict_class}">
      <a class="back" href="../index.html">Back</a>
      <p class="eyebrow">PAPER DIAGNOSTIC</p>
      <h1>{esc(item["arxiv_id"])}</h1>
      <p class="title">{esc(item["title"])}</p>
      <span class="verdict hero-verdict">{esc(verdict_text)}</span>
      <p class="finding-large">{esc(one_line_finding(item))}</p>
    </section>
    <section class="detail-grid">
      {metric("Gold candidates", summary["gold_candidates"])}
      {metric("AI candidates", summary["ai_candidates"])}
      {metric("Matched", summary["matched_candidates"])}
      {metric("Candidate issues", summary["candidate_issues"], "strong" if summary["candidate_issues"] else "")}
      {metric("Identity issues", summary["identity_issues"], "strong" if summary["identity_issues"] else "")}
      {metric("Numeric diffs", summary["quantity_numeric_mismatch"], "strong" if summary["quantity_numeric_mismatch"] else "")}
      {metric("Missing values", summary["quantity_missing"], "strong" if summary["quantity_missing"] else "")}
      {metric("Uncertainty issues", summary["quantity_uncertainty_issues"], "strong" if summary["quantity_uncertainty_issues"] else "")}
      {metric("Unit/format issues", summary["quantity_unit_issues"], "strong" if summary["quantity_unit_issues"] else "")}
      {metric("Aligned items", summary["aligned_items"], "good" if summary["aligned_items"] else "")}
    </section>
    <section class="source-strip">
      <span>Expert <code>{esc(item["gold_path"])}</code></span>
      <span>AI <code>{esc(item["ai_source_path"])}</code></span>
      <span>Status <code>{esc(item["gold_status"])}</code> / <code>{esc(item["ai_status"])}</code></span>
    </section>
    <section class="folds">
      {details_block("Review items", f"{issue_count} item(s)", issue_table, open_by_default=issue_count > 0)}
      {details_block("Aligned items", f"{summary["aligned_items"]} no-review item(s)", aligned_table)}
      {details_block("Matched candidates", f"{len(item["matched_candidates"])} match(es)", f"<ul>{matched}</ul>")}
      {details_block("Expert notes", item["gold_kind"], f"<pre>{esc(item["gold_notes"])}</pre>")}
      {details_block("AI summary", item["ai_source_label"], f"<pre>{esc(item["ai_summary"])}</pre>")}
      {details_block("AI candidate groups", f"{len(item["ai_candidate_groups"])} group(s)", f"<ul>{ai_groups}</ul>")}
    </section>
    """
    return PAGE_TEMPLATE.format(title=f"{item['arxiv_id']} Gold vs AI", body=body)


PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --canvas: #f5fbfa;
      --panel: #ffffff;
      --ink: #17242d;
      --muted: #5e7480;
      --line: #d4e5e2;
      --line-strong: #a8c9c4;
      --cool: #edf8f6;
      --teal: #147f7a;
      --teal-dark: #0d5f5b;
      --teal-soft: #dff4f0;
      --green: #128a58;
      --green-ink: #075c39;
      --green-soft: #dff7ea;
      --green-line: #7fd5aa;
      --red: #d83b35;
      --red-ink: #941f1d;
      --red-soft: #ffe6e2;
      --red-line: #f49a94;
      --warn: #8c6d00;
      --warn-ink: #5f4b00;
      --warn-soft: #fff3c7;
      --warn-line: #d9bd47;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--canvas);
      color: var(--ink);
      font-family: D-DIN, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: 16px;
      line-height: 1.5;
      letter-spacing: 0;
    }}
    main {{ min-height: 100vh; }}
    a {{ color: inherit; text-decoration: none; }}
    h1 {{
      margin: 0;
      color: inherit;
      font-family: D-DIN-Bold, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: clamp(40px, 7vw, 76px);
      font-weight: 700;
      line-height: 0.96;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 18px;
      line-height: 1.2;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    code {{
      padding: 2px 5px;
      border: 1px solid var(--line);
      border-radius: 4px;
      background: var(--cool);
      color: var(--ink);
      font-size: 13px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      font-family: D-DIN, "Arial Narrow", Arial, Verdana, sans-serif;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .hero, .detail-hero {{
      background: var(--teal-soft);
      color: var(--ink);
      padding: 32px;
    }}
    .hero {{
      min-height: clamp(260px, 32vh, 380px);
      display: grid;
      align-content: end;
      gap: 28px;
      border-bottom: 1px solid var(--line-strong);
    }}
    .detail-hero {{
      position: relative;
      min-height: clamp(240px, 30vh, 340px);
      display: grid;
      align-content: end;
      gap: 10px;
      border-bottom: 1px solid var(--line-strong);
    }}
    .detail-hero.clean {{
      background: var(--green-soft);
      border-bottom-color: var(--green-line);
    }}
    .detail-hero.review {{
      background: var(--red-soft);
      border-bottom-color: var(--red-line);
    }}
    .back {{
      position: absolute;
      top: 24px;
      left: 32px;
      border: 1px solid var(--teal);
      border-radius: 32px;
      padding: 12px 18px;
      background: rgba(255, 255, 255, .72);
      color: var(--teal-dark);
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      transition: background .18s ease, color .18s ease, transform .18s ease;
    }}
    .back:hover {{ background: var(--teal); color: #fff; transform: translateY(-1px); }}
    .eyebrow {{
      margin: 0;
      color: currentColor;
      opacity: .68;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .title {{
      max-width: 920px;
      margin: 0;
      color: inherit;
      opacity: .76;
    }}
    .hero-metrics, .detail-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      border-top: 1px solid var(--line-strong);
      border-left: 1px solid var(--line-strong);
    }}
    .metric {{
      min-height: 82px;
      padding: 14px 16px;
      border-right: 1px solid var(--line-strong);
      border-bottom: 1px solid var(--line-strong);
      color: inherit;
    }}
    .metric span {{
      display: block;
      opacity: .66;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .metric strong {{
      display: block;
      margin-top: 6px;
      font-size: 30px;
      line-height: 1;
    }}
    .metric.strong {{
      background: var(--red-soft);
      color: var(--red-ink);
      box-shadow: inset 0 0 0 1px var(--red-line);
    }}
    .metric.good {{
      background: var(--green-soft);
      color: var(--green-ink);
      box-shadow: inset 0 0 0 1px var(--green-line);
    }}
    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 14px 32px;
      border-bottom: 1px solid var(--line);
      background: rgba(245, 251, 250, .9);
      backdrop-filter: blur(12px);
    }}
    .toolbar span {{ margin-left: auto; color: var(--muted); font-size: 13px; }}
    .filter {{
      min-height: 44px;
      border: 1px solid var(--line-strong);
      border-radius: 32px;
      background: var(--panel);
      color: var(--ink);
      padding: 0 18px;
      font: inherit;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      cursor: pointer;
      transition: background .18s ease, color .18s ease, transform .18s ease;
    }}
    .filter:hover, .filter.active {{
      border-color: var(--teal);
      background: var(--teal);
      color: #fff;
      transform: translateY(-1px);
    }}
    .filter[data-filter="review"]:hover,
    .filter[data-filter="review"].active {{
      border-color: var(--red);
      background: var(--red);
    }}
    .filter[data-filter="clean"]:hover,
    .filter[data-filter="clean"].active {{
      border-color: var(--green);
      background: var(--green);
    }}
    .paper-list {{ padding: 24px 32px 56px; }}
    .paper-row {{
      display: grid;
      grid-template-columns: 104px minmax(240px, 1fr) minmax(360px, 44%);
      gap: 18px;
      align-items: stretch;
      min-height: 122px;
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 12px;
      background: var(--panel);
      overflow: hidden;
      transition: border-color .18s ease, transform .18s ease, background .18s ease;
    }}
    .paper-row:hover {{ border-color: var(--teal); transform: translateY(-2px); }}
    .paper-row.clean {{
      border-left: 6px solid var(--green);
      background: var(--green-soft);
    }}
    .paper-row.review {{
      border-left: 6px solid var(--red);
      background: var(--red-soft);
    }}
    .paper-row.hidden {{ display: none; }}
    .verdict {{
      display: grid;
      place-items: center;
      padding: 16px 10px;
      background: var(--red);
      color: #fff;
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .paper-row.clean .verdict {{
      background: var(--green);
      color: #fff;
      border-right: 1px solid var(--green-line);
    }}
    .paper-row.review .verdict {{
      border-right: 1px solid var(--red-line);
    }}
    .paper-main {{
      display: grid;
      align-content: center;
      gap: 5px;
      min-width: 0;
      padding: 16px 0;
    }}
    .paper-main strong {{
      font-size: 26px;
      line-height: 1;
      text-transform: uppercase;
    }}
    .paper-main em {{
      overflow: hidden;
      color: var(--muted);
      font-style: normal;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .finding {{ color: var(--ink); font-size: 14px; }}
    .stat-strip {{
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      border-left: 1px solid rgba(23, 36, 45, .12);
    }}
    .stat {{
      display: grid;
      align-content: center;
      gap: 3px;
      min-width: 0;
      padding: 10px;
      border-left: 1px solid rgba(23, 36, 45, .12);
    }}
    .stat:first-child {{ border-left: 0; }}
    .stat b {{ font-size: 22px; line-height: 1; }}
    .stat small {{ color: var(--muted); font-size: 10px; font-weight: 700; text-transform: uppercase; }}
    .stat.bad {{
      background: rgba(216, 59, 53, .14);
      color: var(--red-ink);
    }}
    .hero-verdict {{
      position: absolute;
      right: 32px;
      top: 28px;
      min-width: 104px;
      min-height: 44px;
      border: 0;
      border-radius: 32px;
      background: var(--green);
      color: #fff;
    }}
    .detail-hero.review .hero-verdict {{ background: var(--red); color: #fff; }}
    .finding-large {{ max-width: 860px; margin: 12px 0 0; font-size: 20px; }}
    .detail-grid {{
      margin: 0;
      padding: 0 32px;
      border-color: var(--line);
    }}
    .detail-grid .metric {{ border-color: var(--line); color: var(--ink); }}
    .source-strip {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 18px;
      padding: 18px 32px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
      background: var(--panel);
    }}
    .folds {{ padding: 24px 32px 56px; }}
    .fold {{
      border: 1px solid var(--line);
      border-radius: 8px;
      margin-bottom: 12px;
      background: var(--panel);
      overflow: hidden;
    }}
    .fold summary {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 58px;
      padding: 0 18px;
      cursor: pointer;
      list-style: none;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .fold summary::-webkit-details-marker {{ display: none; }}
    .fold summary::after {{
      content: "+";
      display: grid;
      place-items: center;
      width: 28px;
      height: 28px;
      border: 1px solid var(--teal);
      border-radius: 50%;
      margin-left: 14px;
      color: var(--teal-dark);
      transition: transform .18s ease;
    }}
    .fold[open] summary::after {{ content: "-"; transform: rotate(180deg); }}
    .fold summary b {{ margin-left: auto; color: var(--muted); font-size: 12px; }}
    .fold-body {{
      border-top: 1px solid var(--line);
      padding: 18px;
      animation: foldIn .18s ease-out;
      overflow-x: auto;
      background: #fff;
    }}
    .issue-table td:nth-child(2) {{
      font-family: D-DIN, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: 13px;
      color: var(--muted);
    }}
    .issue-table td:nth-child(3) {{
      font-family: D-DIN, "Arial Narrow", Arial, Verdana, sans-serif;
      font-size: 13px;
      color: var(--muted);
    }}
    .row-warn td {{ background: var(--warn-soft); }}
    .row-critical td {{ background: var(--red-soft); }}
    .row-bad td {{ background: #fff2ef; }}
    .row-good td {{ background: #fbfffc; }}
    .badge {{
      display: inline-block;
      border: 1px solid var(--green);
      border-radius: 32px;
      padding: 3px 9px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .badge.good {{ border-color: var(--green); background: var(--green); color: #fff; }}
    .badge.bad {{ border-color: var(--red); background: var(--red); color: #fff; }}
    .badge.critical {{ border-color: var(--red-ink); background: var(--red-ink); color: #fff; }}
    .badge.warn {{ border-color: var(--warn); background: var(--warn); color: #fff; }}
    .note {{
      max-width: 360px;
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      text-transform: none;
    }}
    .muted {{ color: var(--muted); }}
    @keyframes foldIn {{
      from {{ opacity: 0; transform: translateY(-4px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}
    @media (max-width: 980px) {{
      .hero-metrics, .detail-grid {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .paper-row {{ grid-template-columns: 86px 1fr; }}
      .stat-strip {{ grid-column: 1 / -1; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--line); border-left: 0; }}
      .stat:nth-child(4) {{ border-left: 0; }}
    }}
    @media (max-width: 640px) {{
      .hero, .detail-hero {{ padding: 24px 18px; }}
      .toolbar, .paper-list, .folds, .source-strip {{ padding-left: 18px; padding-right: 18px; }}
      .toolbar {{ align-items: stretch; flex-wrap: wrap; }}
      .toolbar span {{ width: 100%; margin-left: 0; }}
      .hero-metrics, .detail-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); padding-left: 18px; padding-right: 18px; }}
      .paper-row {{ grid-template-columns: 1fr; }}
      .verdict {{ min-height: 44px; }}
      .paper-main {{ padding: 16px; }}
      .hero-verdict {{ position: static; justify-self: start; margin-top: 12px; }}
    }}
  </style>
</head>
<body><main>{body}</main>
<script>
  const filters = document.querySelectorAll('.filter');
  const rows = document.querySelectorAll('.paper-row');
  filters.forEach((button) => {{
    button.addEventListener('click', () => {{
      filters.forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      const mode = button.dataset.filter;
      rows.forEach((row) => {{
        const visible = mode === 'all' || row.dataset.state === mode;
        row.classList.toggle('hidden', !visible);
      }});
    }});
  }});
</script>
</body>
</html>
"""


def detail_filename(index: int, item: dict[str, Any]) -> str:
    suffix = "-draft" if item["gold_kind"] == "draft_checkpoint" else ""
    return f"{index:02d}-{item['arxiv_id']}{suffix}.html"


def clean_html(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()) + "\n"


def write_site(index_path: Path, data: dict[str, Any]) -> list[Path]:
    pages_dir = index_path.parent / "papers"
    pages_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    current_pages: set[Path] = set()
    for index, item in enumerate(data["comparisons"], start=1):
        filename = detail_filename(index, item)
        item["detail_href"] = f"papers/{filename}"
        detail_path = pages_dir / filename
        detail_path.write_text(clean_html(render_detail_html(item)), encoding="utf-8")
        current_pages.add(detail_path)
        written.append(detail_path)
    for stale_path in pages_dir.glob("*.html"):
        if stale_path not in current_pages:
            stale_path.unlink()
    index_path.write_text(clean_html(render_index_html(data)), encoding="utf-8")
    return [index_path, *written]


def main() -> int:
    from stella.lit.env import load_env_files

    load_env_files(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gold-dir",
        type=Path,
        default=Path(os.environ[GOLD_DIR_ENV]).expanduser()
        if os.environ.get(GOLD_DIR_ENV)
        else None,
        help=f"External private gold annotation root. Default: ${GOLD_DIR_ENV}.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output index path. Default: <gold-dir>/../comparison/index.html.",
    )
    args = parser.parse_args()
    if args.gold_dir is None:
        raise SystemExit(
            f"Set {GOLD_DIR_ENV} or pass --gold-dir to the external private "
            "gold annotation root."
        )
    gold_dir = args.gold_dir.expanduser().resolve()
    output = (
        args.output.expanduser()
        if args.output is not None
        else gold_dir.parent / "comparison" / "index.html"
    )
    data = build_data(gold_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    written = write_site(output, data)
    print("Wrote")
    for path in written:
        print(f"- {repo_path(path)}")
    print(json.dumps(data["totals"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
