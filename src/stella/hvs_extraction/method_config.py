"""Frozen method configuration for the hvs_candidate_extraction pipeline.

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


PIPELINE_NAME = "hvs_candidate_extraction"


class HvsExtractionRunConfigSchema(StrictModel):
    name: Literal["hvs_extraction.method_config"]
    version: Literal[1]


class HvsModelRoute(StrictModel):
    """One frozen model route.

    ``seed_honored`` records the D023 capability probe: whether this provider
    route accepts and honors an explicit seed. When it is ``False`` the route
    is still freezable, but exact sample reproduction is not guaranteed and no
    seed-level reproducibility may be claimed.

    ``request_overrides`` carries extraction-local provider overrides merged into
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


class HvsContextBudget(StrictModel):
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


class HvsComponentHashes(StrictModel):
    """Frozen fingerprints of every method-affecting component (D051 gate)."""

    rule_profile_sha256: dict[str, str] = {}
    prompt_template_sha256: dict[str, str] = {}
    submission_schema_sha256: dict[str, str] = {}


class HvsExtractionMethodConfig(StrictModel):
    """HVS extraction run identity; placeholder until ``assert_frozen`` passes."""

    schema_: HvsExtractionRunConfigSchema = Field(
        default=HvsExtractionRunConfigSchema(
            name="hvs_extraction.method_config", version=1
        ),
        alias="schema",
    )
    pipeline: Literal["hvs_candidate_extraction"] = PIPELINE_NAME
    roster_model: HvsModelRoute = HvsModelRoute()
    core_field_model: HvsModelRoute = HvsModelRoute()
    roster_context_budget: HvsContextBudget = HvsContextBudget()
    field_context_budget: HvsContextBudget = HvsContextBudget()
    components: HvsComponentHashes = HvsComponentHashes()

    def method_fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", by_alias=True))

    def unfrozen_fields(self) -> list[str]:
        missing: list[str] = []
        for route_name in ("roster_model", "core_field_model"):
            route = getattr(self, route_name)
            for field_name, value in route.model_dump().items():
                if value is None:
                    missing.append(f"{route_name}.{field_name}")
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
                "extraction method config is not frozen; unset fields: "
                + ", ".join(missing)
            )


def new_hvs_extraction_method_config() -> HvsExtractionMethodConfig:
    """Return the empty placeholder config; it cannot drive a real run."""

    return HvsExtractionMethodConfig()


def default_hvs_extraction_method_config(workspace) -> HvsExtractionMethodConfig:
    """The user-approved frozen method values.

    Roster extractor (D061, accepted 2026-07-25): a single glm-5.2 call with
    thinking enabled, streaming transport (non-streaming long thinking
    generations hit the gateway idle timeout), temperature 0 / top_p 1,
    ``reserve_output`` 64000. Core-field extraction uses deepseek-v4-pro at
    temperature 0 / top_p 1.
    Both providers use a conservative 900K context limit against a nominal
    1M window (user-confirmed). ``seed_honored`` stays False because the
    authorized provider capability probe (2026-07-24) showed the route
    accepts but does not honor explicit seeds; no seed-level reproducibility
    is claimed.
    """

    from stella.hvs_extraction.field_prompts import build_field_prompts
    from stella.hvs_extraction.field_schema import build_field_submission_schema
    from stella.hvs_extraction.roster_prompts import build_extractor_prompts
    from stella.hvs_extraction.submission_schema import build_roster_submission_schema
    from stella.lit.extraction_rules import rule_profile_sha256

    extractor = HvsModelRoute(
        provider="bigmodel",
        model="glm-5.2",
        structured_output_mode="tool_submission",
        temperature=0.0,
        top_p=1.0,
        seed_honored=False,
        request_overrides={"thinking": {"type": "enabled"}},
        stream=True,
    )
    core_field_model = HvsModelRoute(
        provider="deepseek",
        model="deepseek-v4-pro",
        structured_output_mode="tool_submission",
        temperature=0.0,
        top_p=1.0,
        seed_honored=False,
    )
    roster_budget = HvsContextBudget(
        model_context_limit=900000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=0,
        reserve_output=64000,
        reserve_provider_framing=1000,
    )
    field_budget = HvsContextBudget(
        model_context_limit=900000,
        reserve_system_and_rules=8000,
        reserve_tool_schema=4000,
        reserve_candidate_suffix=2000,
        reserve_output=8000,
        reserve_provider_framing=1000,
    )

    extractor_prompts = build_extractor_prompts(workspace, "<MANUSCRIPT>")
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
    components = HvsComponentHashes(
        rule_profile_sha256={
            profile: rule_profile_sha256(workspace, profile)
            for profile in (
                "hvs_candidate_roster",
                "hvs_candidate_core_fields_tex",
                "hvs_candidate_core_fields_tex_ecsv",
            )
        },
        prompt_template_sha256={
            "roster_model": canonical_sha256(
                {"system": extractor_prompts["system"], "user": extractor_prompts["user"]}
            ),
            "core_field_model_tex": canonical_sha256(
                {
                    "system": field_prompts_tex["system"],
                    "user": field_prompts_tex["user"],
                }
            ),
            "core_field_model_tex_ecsv": canonical_sha256(
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
    config = HvsExtractionMethodConfig(
        roster_model=extractor,
        core_field_model=core_field_model,
        roster_context_budget=roster_budget,
        field_context_budget=field_budget,
        components=components,
    )
    config.assert_frozen()
    return config
