"""Frozen method configuration for the hvs_contribution_extraction pipeline.

Structure only: every method-affecting value stays ``None`` until a user
authorizes concrete model routes and budgets. The neutral route, budget,
component-hash, and roster request-policy primitives are shared with the V6
pipeline because their semantics are identical; no V6 writer or reader is
modified.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from stella.lit.extraction.hashing import canonical_sha256
from stella.lit.extraction.method import (
    HvsComponentHashes,
    HvsContextBudget,
    HvsModelRoute,
    HvsRosterRequestPolicy,
    _validate_request_ladder,
)
from stella.lit.schema_models import StrictModel
from stella.lit.extraction_rules import CONTRIBUTION_PROFILE_ID

PIPELINE_NAME = "hvs_contribution_extraction"
CONTRIBUTION_RULE_PROFILE = CONTRIBUTION_PROFILE_ID


class HvsContributionMethodConfigSchema(StrictModel):
    name: Literal["hvs_contribution_extraction.method_config"] = (
        "hvs_contribution_extraction.method_config"
    )
    version: Literal[1] = 1


class HvsContributionQuantityRequestPolicy(StrictModel):
    """Per-object quantity-stage request policy (fingerprinted).

    Same accounting layers as the V6 field policy, scoped to one object's
    quantity stage. The multivalue peer-consistency audit stays disabled
    in v1 by design: enabling a re-examination-only audit is an expert
    decision, and no value is ever copied between objects.
    """

    scope: Literal["per_object_quantity_stage"] = "per_object_quantity_stage"
    max_scientific_requests: int = 4
    max_transport_retries_per_call: int = 2
    max_total_physical_requests: int = 12
    max_format_correction_rounds: int = 2
    shared_across: list[str] = [
        "initial",
        "format_correction",
        "evidence_correction",
    ]

    @model_validator(mode="after")
    def _check(self) -> "HvsContributionQuantityRequestPolicy":
        _validate_request_ladder(
            max_scientific_requests=self.max_scientific_requests,
            max_transport_retries_per_call=self.max_transport_retries_per_call,
            max_total_physical_requests=self.max_total_physical_requests,
            max_format_correction_rounds=self.max_format_correction_rounds,
        )
        return self


class HvsContributionMethodConfig(StrictModel):
    """Contribution pipeline run identity; placeholder until frozen."""

    schema_: HvsContributionMethodConfigSchema = Field(
        default=HvsContributionMethodConfigSchema(),
        alias="schema",
    )
    pipeline: Literal["hvs_contribution_extraction"] = PIPELINE_NAME
    roster_model: HvsModelRoute = HvsModelRoute()
    quantity_model: HvsModelRoute = HvsModelRoute()
    roster_context_budget: HvsContextBudget = HvsContextBudget()
    quantity_context_budget: HvsContextBudget = HvsContextBudget()
    roster_request_policy: HvsRosterRequestPolicy = HvsRosterRequestPolicy()
    quantity_request_policy: HvsContributionQuantityRequestPolicy = (
        HvsContributionQuantityRequestPolicy()
    )
    # v1 leaves the multivalue peer audit disabled; the method fingerprint
    # records this so a later expert decision to enable it changes identity.
    quantity_peer_audit_enabled: Literal[False] = False
    components: HvsComponentHashes = HvsComponentHashes()

    def method_fingerprint(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", by_alias=True))

    def unfrozen_fields(self) -> list[str]:
        missing: list[str] = []
        for route_name in ("roster_model", "quantity_model"):
            route = getattr(self, route_name)
            for field_name, value in route.model_dump().items():
                if value is None:
                    missing.append(f"{route_name}.{field_name}")
        for budget_name in ("roster_context_budget", "quantity_context_budget"):
            budget = getattr(self, budget_name)
            if not budget.is_complete():
                missing.append(budget_name)
        if CONTRIBUTION_RULE_PROFILE not in self.components.rule_profile_sha256:
            missing.append(f"components.rule_profile_sha256.{CONTRIBUTION_RULE_PROFILE}")
        if not self.components.prompt_template_sha256:
            missing.append("components.prompt_template_sha256")
        if not self.components.submission_schema_sha256:
            missing.append("components.submission_schema_sha256")
        return missing

    def assert_frozen(self) -> None:
        missing = self.unfrozen_fields()
        if missing:
            raise ValueError(
                "contribution method config is not frozen; unset fields: "
                + ", ".join(missing)
            )


def new_contribution_method_config() -> HvsContributionMethodConfig:
    """Return the empty placeholder config; it cannot drive a real run."""

    return HvsContributionMethodConfig()
