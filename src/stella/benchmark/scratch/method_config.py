"""Frozen method configuration for the hvs_extraction_scratch pipeline.

Structure only: every method-affecting value stays ``None`` until the user
approves the concrete model routes, sampling settings, and context budgets
(decisions D020, D023, D047, D053). ``assert_frozen`` is the gate that keeps
unfrozen placeholder configs away from real model requests (D051
implementation gate).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from stella.benchmark.run_contract import canonical_sha256
from stella.lit.schema_models import StrictModel


PIPELINE_NAME = "hvs_extraction_scratch"


class ScratchRunConfigSchema(StrictModel):
    name: Literal["benchmark.hvs_extraction_scratch.run_config"]
    version: Literal[1]


class ScratchModelRoute(StrictModel):
    """One frozen model route.

    ``seed_honored`` records the D023 capability probe: whether this provider
    route accepts and honors an explicit seed. When it is ``False`` the route
    is still freezable, but exact sample reproduction is not guaranteed and no
    seed-level reproducibility may be claimed.

    ``request_overrides`` carries scratch-local provider overrides merged into
    the request after the shared structured-output contract is applied (dev-run
    evidence, 2026-07-24: the glm-5.2 adjudicator's thinking mode consumes the
    whole output reserve before any tool call, so thinking is disabled for this
    route only; the shared route table and the formal review path stay
    untouched).

    ``stream`` requests streaming transport. Long thinking generations
    (measured at ~17K reasoning tokens for this task) outlive gateway idle
    timeouts on a silent connection; streaming keeps bytes flowing so the
    request survives (2026-07-24 stream probe: finish_reason=stop with a clean
    tool call after 262 s). Streaming routes get a longer read timeout.
    """

    provider: str | None = None
    model: str | None = None
    structured_output_mode: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    seed_honored: bool | None = None
    request_overrides: dict[str, Any] = {}
    stream: bool = False


class ScratchContextBudget(StrictModel):
    """D053 preflight budget: exact context limit minus conservative reserves."""

    model_context_limit: int | None = None
    reserve_system_and_rules: int | None = None
    reserve_tool_schema: int | None = None
    reserve_candidate_suffix: int | None = None
    reserve_output: int | None = None
    reserve_provider_framing: int | None = None

    def is_complete(self) -> bool:
        return all(
            value is not None
            for value in (
                self.model_context_limit,
                self.reserve_system_and_rules,
                self.reserve_tool_schema,
                self.reserve_candidate_suffix,
                self.reserve_output,
                self.reserve_provider_framing,
            )
        )

    def input_budget(self) -> int:
        if not self.is_complete():
            raise ValueError("context budget is not fully populated")
        return self.model_context_limit - (
            self.reserve_system_and_rules
            + self.reserve_tool_schema
            + self.reserve_candidate_suffix
            + self.reserve_output
            + self.reserve_provider_framing
        )


class ScratchComponentHashes(StrictModel):
    """Frozen fingerprints of every method-affecting component (D051 gate)."""

    rule_profile_sha256: dict[str, str] = {}
    prompt_template_sha256: dict[str, str] = {}
    submission_schema_sha256: dict[str, str] = {}


class ScratchMethodConfig(StrictModel):
    """Scratch run identity; placeholder until ``assert_frozen`` passes."""

    schema_: ScratchRunConfigSchema = Field(
        default=ScratchRunConfigSchema(
            name="benchmark.hvs_extraction_scratch.run_config", version=1
        ),
        alias="schema",
    )
    pipeline: Literal["hvs_extraction_scratch"] = PIPELINE_NAME
    roster_extractor: ScratchModelRoute = ScratchModelRoute()
    roster_adjudicator: ScratchModelRoute = ScratchModelRoute()
    field_extractor: ScratchModelRoute = ScratchModelRoute()
    roster_extractor_seeds: tuple[int, int, int] | None = None
    roster_context_budget: ScratchContextBudget = ScratchContextBudget()
    field_context_budget: ScratchContextBudget = ScratchContextBudget()
    components: ScratchComponentHashes = ScratchComponentHashes()

    def method_fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", by_alias=True))

    def unfrozen_fields(self) -> list[str]:
        missing: list[str] = []
        for route_name in ("roster_extractor", "roster_adjudicator", "field_extractor"):
            route = getattr(self, route_name)
            for field_name, value in route.model_dump().items():
                if value is None:
                    missing.append(f"{route_name}.{field_name}")
        if (
            self.roster_extractor.seed_honored
            and self.roster_extractor_seeds is None
        ):
            missing.append("roster_extractor_seeds")
        for budget_name in ("roster_context_budget", "field_context_budget"):
            budget = getattr(self, budget_name)
            if not budget.is_complete():
                missing.append(budget_name)
        if not self.components.rule_profile_sha256:
            missing.append("components.rule_profile_sha256")
        if not self.components.prompt_template_sha256:
            missing.append("components.prompt_template_sha256")
        if not self.components.submission_schema_sha256:
            missing.append("components.submission_schema_sha256")
        return missing

    def assert_frozen(self) -> None:
        missing = self.unfrozen_fields()
        if missing:
            raise ValueError(
                "scratch method config is not frozen; unset fields: "
                + ", ".join(missing)
            )


def new_scratch_method_config() -> ScratchMethodConfig:
    """Return the empty placeholder config; it cannot drive a real run."""

    return ScratchMethodConfig()


def default_scratch_method_config(workspace) -> ScratchMethodConfig:
    """The user-approved frozen method values (2026-07-23, Phase 3 gate).

    Extractor and field extractor: deepseek-v4-pro at temperature 0.2 / top_p 1
    (D023). Adjudicator: glm-5.2 at temperature 0, a distinct model family.
    Both routes use a conservative 900K context limit against a nominal 1M
    window (user-confirmed for both providers). ``seed_honored`` stays False
    until the authorized provider capability probe proves the route accepts
    and honors explicit seeds; no seed-level reproducibility is claimed
    before then (D023). The adjudicator carries a scratch-local
    ``thinking: disabled`` override: dev-run evidence (2026-07-24) showed
    glm-5.2's thinking mode consumes the entire output reserve on reasoning
    tokens and truncates before any tool call (finish_reason=length); with
    thinking disabled the route returns clean tool calls.
    """

    from stella.benchmark.scratch.field_prompts import build_field_prompts
    from stella.benchmark.scratch.field_schema import build_field_submission_schema
    from stella.benchmark.scratch.roster_prompts import (
        build_adjudicator_prompts,
        build_extractor_prompts,
    )
    from stella.benchmark.scratch.submission_schema import build_roster_submission_schema
    from stella.lit.extraction_rules import rule_profile_sha256

    extractor = ScratchModelRoute(
        provider="deepseek",
        model="deepseek-v4-pro",
        structured_output_mode="tool_submission",
        temperature=0.2,
        top_p=1.0,
        seed_honored=False,
    )
    adjudicator = ScratchModelRoute(
        provider="bigmodel",
        model="glm-5.2",
        structured_output_mode="tool_submission",
        temperature=0.0,
        top_p=1.0,
        seed_honored=False,
        request_overrides={"thinking": {"type": "disabled"}},
    )
    roster_budget = ScratchContextBudget(
        model_context_limit=900000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=0,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )
    field_budget = ScratchContextBudget(
        model_context_limit=900000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=2000,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )

    extractor_prompts = build_extractor_prompts(workspace, "<MANUSCRIPT>")
    adjudicator_prompts = build_adjudicator_prompts(
        workspace, "<MANUSCRIPT>", [("Proposal A", {})]
    )
    field_prompts_tex = build_field_prompts(
        workspace,
        manuscript_view="<MANUSCRIPT>",
        ecsv_blocks=[],
        assigned_candidate_json="<CANDIDATE>",
    )
    field_prompts_ecsv = build_field_prompts(
        workspace,
        manuscript_view="<MANUSCRIPT>",
        ecsv_blocks=["<ECSV_BLOCK>"],
        assigned_candidate_json="<CANDIDATE>",
    )
    components = ScratchComponentHashes(
        rule_profile_sha256={
            profile: rule_profile_sha256(workspace, profile)
            for profile in (
                "hvs_roster_scratch",
                "hvs_field_extractor_scratch_tex",
                "hvs_field_extractor_scratch_tex_ecsv",
            )
        },
        prompt_template_sha256={
            "roster_extractor": canonical_sha256(
                {"system": extractor_prompts["system"], "user": extractor_prompts["user"]}
            ),
            "roster_adjudicator": canonical_sha256(
                {
                    "system": adjudicator_prompts["system"],
                    "user": adjudicator_prompts["user"],
                }
            ),
            "field_extractor_tex": canonical_sha256(
                {
                    "system": field_prompts_tex["system"],
                    "user": field_prompts_tex["user"],
                }
            ),
            "field_extractor_tex_ecsv": canonical_sha256(
                {
                    "system": field_prompts_ecsv["system"],
                    "user": field_prompts_ecsv["user"],
                }
            ),
        },
        submission_schema_sha256={
            "submit_candidate_roster": canonical_sha256(
                build_roster_submission_schema(["<RUNTIME_TEX_PATH>"])
            ),
            "submit_candidate_fields": canonical_sha256(
                build_field_submission_schema(
                    ["<RUNTIME_TEX_PATH>"], ["<RUNTIME_ECSV_PATH>"]
                )
            ),
        },
    )
    config = ScratchMethodConfig(
        roster_extractor=extractor,
        roster_adjudicator=adjudicator,
        field_extractor=extractor,
        roster_extractor_seeds=(101, 202, 303),
        roster_context_budget=roster_budget,
        field_context_budget=field_budget,
        components=components,
    )
    config.assert_frozen()
    return config
