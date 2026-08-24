"""Load, validate, render, and fingerprint extraction-rule profiles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml


CONTRIBUTION_RULES_RELATIVE_DIR = Path("contracts/hvs-contributions/rules")
CONTRIBUTION_MODULE_FILENAMES = (
    "paper-claims.yaml",
    "hvs-contributions-roster.yaml",
    "hvs-contributions-quantities.yaml",
)
RULES_RELATIVE_DIR = Path("skills/hvs-candidates-extraction/rules")
MODULE_FILENAMES = (
    "paper-claims.yaml",
    "hvs-roster.yaml",
    "hvs-core-fields.yaml",
)
PROFILES_FILENAME = "profiles.yaml"
CONTRIBUTION_PROFILE_ID = "hvs_contribution_v1"
CONTRIBUTION_PROFILE_RULE_PREFIX = "hvs.contrib."
CANONICAL_PROFILES = frozenset(
    {
        "hvs_candidate_roster",
        "hvs_candidate_core_fields_tex",
        "hvs_candidate_core_fields_tex_ecsv",
        "coding_agent_baseline",
    }
)
REQUIRED_PROFILES = CANONICAL_PROFILES
CANONICAL_FIELD_PROFILE_PAIR = (
    "hvs_candidate_core_fields_tex",
    "hvs_candidate_core_fields_tex_ecsv",
)
GENERATED_VIEW_PROFILES = {
    Path("skills/hvs-candidates-extraction/SKILL.md"): "coding_agent_baseline",
    Path("benchmark/GUIDELINE.md"): CONTRIBUTION_PROFILE_ID,
}


@dataclass(frozen=True)
class ExtractionRule:
    id: str
    title: str
    text: str
    module_id: str


@dataclass(frozen=True)
class RuleCatalog:
    rules: dict[str, ExtractionRule]
    profiles: dict[str, tuple[str, ...]]

    def profile_rules(self, profile_id: str) -> tuple[ExtractionRule, ...]:
        rule_ids = self.profiles.get(profile_id)
        if rule_ids is None:
            raise ValueError(f"unknown extraction rule profile: {profile_id}")
        return tuple(self.rules[rule_id] for rule_id in rule_ids)


def _load_yaml_mapping(path: Path) -> dict:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping in {path}")
    return payload


def _require_exact_keys(value: dict, expected: set[str], location: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {missing}")
        if extra:
            details.append(f"unexpected {extra}")
        raise ValueError(f"{location}: {'; '.join(details)}")


def _required_text(value: object, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}: expected non-empty text")
    return value.strip()


def _load_rule_modules(
    workspace: Path, rules_dir_relative: Path, module_filenames: tuple[str, ...]
) -> dict[str, ExtractionRule]:
    """Load rule module files with strict shape checks."""

    rules_dir = workspace / rules_dir_relative
    rules: dict[str, ExtractionRule] = {}
    module_ids: set[str] = set()
    for filename in module_filenames:
        path = rules_dir / filename
        payload = _load_yaml_mapping(path)
        _require_exact_keys(payload, {"module_id", "rules"}, str(path))
        module_id = _required_text(payload["module_id"], f"{path}.module_id")
        if module_id in module_ids:
            raise ValueError(f"duplicate extraction rule module id: {module_id}")
        module_ids.add(module_id)
        records = payload["rules"]
        if not isinstance(records, list) or not records:
            raise ValueError(f"{path}.rules: expected non-empty list")
        for index, record in enumerate(records):
            location = f"{path}.rules[{index}]"
            if not isinstance(record, dict):
                raise ValueError(f"{location}: expected mapping")
            _require_exact_keys(record, {"id", "title", "text"}, location)
            rule_id = _required_text(record["id"], f"{location}.id")
            if rule_id in rules:
                raise ValueError(f"duplicate extraction rule id: {rule_id}")
            rules[rule_id] = ExtractionRule(
                id=rule_id,
                title=_required_text(record["title"], f"{location}.title"),
                text=_required_text(record["text"], f"{location}.text"),
                module_id=module_id,
            )
    return rules


def _load_profiles(
    workspace: Path,
    rules_dir_relative: Path,
    rules: dict[str, ExtractionRule],
    required_profiles: frozenset[str],
) -> dict[str, tuple[str, ...]]:
    profiles_path = workspace / rules_dir_relative / PROFILES_FILENAME
    profiles_payload = _load_yaml_mapping(profiles_path)
    _require_exact_keys(profiles_payload, {"profiles"}, str(profiles_path))
    raw_profiles = profiles_payload["profiles"]
    if not isinstance(raw_profiles, dict):
        raise ValueError(f"{profiles_path}.profiles: expected mapping")
    if set(raw_profiles) != set(required_profiles):
        missing = sorted(set(required_profiles) - set(raw_profiles))
        extra = sorted(set(raw_profiles) - set(required_profiles))
        raise ValueError(
            f"{profiles_path}.profiles must be exactly the required profiles; "
            f"missing={missing}, unexpected={extra}"
        )
    profiles: dict[str, tuple[str, ...]] = {}
    used_rule_ids: set[str] = set()
    for profile_id, raw_rule_ids in raw_profiles.items():
        if not isinstance(raw_rule_ids, list) or not raw_rule_ids:
            raise ValueError(f"profile {profile_id}: expected non-empty rule-id list")
        rule_ids: list[str] = []
        for index, raw_rule_id in enumerate(raw_rule_ids):
            rule_id = _required_text(raw_rule_id, f"profile {profile_id}[{index}]")
            if rule_id not in rules:
                raise ValueError(f"profile {profile_id}: unknown rule id {rule_id}")
            if rule_id in rule_ids:
                raise ValueError(f"profile {profile_id}: duplicate rule id {rule_id}")
            rule_ids.append(rule_id)
        profiles[str(profile_id)] = tuple(rule_ids)
        used_rule_ids.update(rule_ids)
    unused = sorted(set(rules) - used_rule_ids)
    if unused:
        raise ValueError(f"extraction rules are not used by any profile: {unused}")
    return profiles


def load_contribution_rule_catalog(workspace: Path) -> RuleCatalog:
    """Load the public contribution rules from contracts/."""

    rules = _load_rule_modules(
        workspace, CONTRIBUTION_RULES_RELATIVE_DIR, CONTRIBUTION_MODULE_FILENAMES
    )
    profiles = _load_profiles(
        workspace,
        CONTRIBUTION_RULES_RELATIVE_DIR,
        rules,
        frozenset({CONTRIBUTION_PROFILE_ID}),
    )
    contribution_rules = profiles[CONTRIBUTION_PROFILE_ID]
    forbidden = {
        rule_id
        for rule_id in contribution_rules
        if rule_id.startswith(("hvs.roster.", "hvs.field."))
    }
    if forbidden:
        raise ValueError(
            f"profile {CONTRIBUTION_PROFILE_ID} must not contain V6 roster or "
            f"core-field rules: {sorted(forbidden)}"
        )
    return RuleCatalog(rules=rules, profiles=profiles)


def load_candidate_rule_catalog(workspace: Path) -> RuleCatalog:
    """Load the legacy candidate rules from the retired skills directory."""

    rules = _load_rule_modules(workspace, RULES_RELATIVE_DIR, MODULE_FILENAMES)
    profiles = _load_profiles(workspace, RULES_RELATIVE_DIR, rules, REQUIRED_PROFILES)
    tex_profile, tex_ecsv_profile = CANONICAL_FIELD_PROFILE_PAIR
    difference = set(profiles[tex_profile]) - set(profiles[tex_ecsv_profile])
    if difference:
        raise ValueError(
            f"profile {tex_profile} is not a subset of {tex_ecsv_profile}: "
            f"{sorted(difference)}"
        )
    staged_union = (
        set(profiles["hvs_candidate_roster"])
        | set(profiles["hvs_candidate_core_fields_tex_ecsv"])
    )
    if set(profiles["coding_agent_baseline"]) != staged_union:
        raise ValueError(
            "profile coding_agent_baseline must contain exactly the canonical "
            "roster and TeX+ECSV core-field rules"
        )
    for profile_id in ("hvs_candidate_roster", "coding_agent_baseline"):
        for required in ("hvs.roster.final_treatment", "hvs.roster.prior_reassessment"):
            if required not in profiles[profile_id]:
                raise ValueError(f"profile {profile_id} must retain {required}")
    return RuleCatalog(rules=rules, profiles=profiles)


def load_rule_catalog(workspace: Path) -> RuleCatalog:
    """Load the merged transitional catalog (contribution + candidate)."""

    contribution = load_contribution_rule_catalog(workspace)
    candidate = load_candidate_rule_catalog(workspace)
    rules: dict[str, ExtractionRule] = dict(contribution.rules)
    for rule_id, rule in candidate.rules.items():
        existing = rules.get(rule_id)
        if existing is not None:
            if (existing.title, existing.text) != (rule.title, rule.text):
                raise ValueError(
                    f"shared rule {rule_id} differs between contracts and skills"
                )
            continue
        rules[rule_id] = rule
    profiles = {**contribution.profiles, **candidate.profiles}
    return RuleCatalog(rules=rules, profiles=profiles)


def _catalog_for_profile(workspace: Path, profile_id: str) -> RuleCatalog:
    """Load only the rule directory that owns the requested profile."""

    if profile_id == CONTRIBUTION_PROFILE_ID:
        return load_contribution_rule_catalog(workspace)
    return load_candidate_rule_catalog(workspace)


def _canonical_profile_payload(
    catalog: RuleCatalog, profile_id: str
) -> list[dict[str, str]]:
    return [
        {"id": rule.id, "title": rule.title, "text": rule.text}
        for rule in catalog.profile_rules(profile_id)
    ]


def rule_profile_sha256(workspace: Path, profile_id: str) -> str:
    payload = _canonical_profile_payload(
        _catalog_for_profile(workspace, profile_id), profile_id
    )
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def render_rule_profile(
    workspace: Path,
    profile_id: str,
    format: Literal["markdown", "prompt"] = "prompt",
) -> str:
    rules = _catalog_for_profile(workspace, profile_id).profile_rules(profile_id)
    if format == "prompt":
        blocks = [f"[{rule.id}] {rule.title}\n{rule.text}" for rule in rules]
    elif format == "markdown":
        blocks = [f"### `{rule.id}` — {rule.title}\n\n{rule.text}" for rule in rules]
    else:
        raise ValueError(f"unsupported extraction rule render format: {format}")
    return "\n\n".join(blocks) + "\n"


def _profile_markers(profile_id: str) -> tuple[str, str]:
    return (
        f"<!-- BEGIN GENERATED RULE PROFILE: {profile_id} -->",
        f"<!-- END GENERATED RULE PROFILE: {profile_id} -->",
    )


def _replace_profile_block(text: str, profile_id: str, rendered: str, path: Path) -> str:
    start_marker, end_marker = _profile_markers(profile_id)
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise ValueError(f"{path}: expected exactly one marker pair for {profile_id}")
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker)
    if end < start:
        raise ValueError(f"{path}: generated markers are out of order for {profile_id}")
    return text[:start] + "\n\n" + rendered.rstrip() + "\n\n" + text[end:]



def generated_rule_views(workspace: Path) -> dict[Path, str]:
    """Return complete committed views with generated marker blocks refreshed."""

    generated: dict[Path, str] = {}
    for relative_path, profile_id in GENERATED_VIEW_PROFILES.items():
        path = workspace / relative_path
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current:
            rendered = render_rule_profile(workspace, profile_id, format="markdown")
            generated[relative_path] = _replace_profile_block(
                current, profile_id, rendered, relative_path
            )
    return generated


def stale_generated_rule_views(workspace: Path) -> list[Path]:
    stale: list[Path] = []
    for relative_path, expected in generated_rule_views(workspace).items():
        path = workspace / relative_path
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != expected:
            stale.append(relative_path)
    return stale


def assert_generated_rule_views_current(workspace: Path) -> None:
    stale = stale_generated_rule_views(workspace)
    if stale:
        joined = ", ".join(path.as_posix() for path in stale)
        raise ValueError(
            "generated extraction rule views are stale: "
            f"{joined}; run scripts/generate_extraction_rule_views.py"
        )


def write_generated_rule_views(workspace: Path) -> list[Path]:
    changed: list[Path] = []
    for relative_path, expected in generated_rule_views(workspace).items():
        path = workspace / relative_path
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == expected:
            continue
        temporary = path.with_name(path.name + ".tmp")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(expected, encoding="utf-8")
        temporary.replace(path)
        changed.append(relative_path)
    return changed
