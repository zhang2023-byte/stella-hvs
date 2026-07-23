"""Frozen method configuration for the hvs_extraction_scratch pipeline.

Structure only: every method-affecting value stays ``None`` until the user
approves the concrete model routes, sampling settings, and context budgets
(decisions D020, D023, D047, D053). ``assert_frozen`` is the gate that keeps
unfrozen placeholder configs away from real model requests (D051
implementation gate).
"""

from __future__ import annotations

from typing import Literal

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
    """

    provider: str | None = None
    model: str | None = None
    structured_output_mode: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    seed_honored: bool | None = None


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
