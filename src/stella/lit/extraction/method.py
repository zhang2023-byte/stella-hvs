"""Shared frozen method-configuration primitives for extraction pipelines.

Route, budget, component-hash, and request-ladder models shared by the
contribution extractor and, during the retirement transition, by the legacy
candidate pipeline that still imports them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import model_validator

from stella.lit.extraction.bounded_call import MAX_TRANSPORT_ATTEMPTS
from stella.lit.schema_models import StrictModel

class HvsModelRoute(StrictModel):
    """One frozen model route.

    ``seed_honored`` records whether a capability probe confirmed the provider
    route accepts and honors an explicit seed. When it is ``False`` the route
    is still freezable, but exact sample reproduction is not guaranteed and no
    seed-level reproducibility may be claimed.

    ``request_overrides`` carries extraction-local provider overrides merged
    into the request after the shared structured-output contract is applied.

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
    """Preflight budget: exact context limit minus conservative reserves."""

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
    """Frozen fingerprints of every method-affecting component."""

    rule_profile_sha256: dict[str, str] = {}
    prompt_template_sha256: dict[str, str] = {}
    submission_schema_sha256: dict[str, str] = {}
    semantic_implementation_sha256: dict[str, str] = {}

def _validate_request_ladder(
    *,
    max_scientific_requests: int,
    max_transport_retries_per_call: int,
    max_total_physical_requests: int,
    max_format_correction_rounds: int,
) -> None:
    """Shared policy invariants for one extraction unit's request ladder."""

    if max_scientific_requests < 1:
        raise ValueError("max_scientific_requests must be at least 1")
    if max_transport_retries_per_call < 0:
        raise ValueError("max_transport_retries_per_call must not be negative")
    if max_transport_retries_per_call > MAX_TRANSPORT_ATTEMPTS - 1:
        raise ValueError(
            "max_transport_retries_per_call cannot exceed the per-call "
            f"transport attempt bound ({MAX_TRANSPORT_ATTEMPTS - 1}); larger "
            "values would silently never take effect"
        )
    if max_format_correction_rounds < 1:
        raise ValueError("max_format_correction_rounds must be at least 1")
    if max_scientific_requests < 1 + max_format_correction_rounds + 1:
        raise ValueError(
            "max_scientific_requests must cover the initial request, every "
            "format-correction round, and one evidence correction "
            f"(at least {1 + max_format_correction_rounds + 1})"
        )
    if max_total_physical_requests < max_scientific_requests * (
        1 + max_transport_retries_per_call
    ):
        raise ValueError(
            "max_total_physical_requests must cover the full correction "
            "ladder with per-call retries (at least "
            f"{max_scientific_requests * (1 + max_transport_retries_per_call)})"
        )

class HvsRosterRequestPolicy(StrictModel):
    """Per-slot roster-stage request policy (fingerprinted).

    Same accounting layers as the field policy, scoped to one roster
    extractor slot: scientific slots bound the initial request, the bounded
    format-correction ladder, and one evidence correction; transport retries
    draw on a per-logical-call pool; the hard physical ceiling keeps one
    spare request over the maximal ladder so terminal classifications stay
    identical to the legacy shared-ledger behavior.
    """

    scope: Literal["per_slot_roster_stage"] = "per_slot_roster_stage"
    max_scientific_requests: int = 3
    max_transport_retries_per_call: int = 2
    max_total_physical_requests: int = 10
    max_format_correction_rounds: int = 1
    shared_across: list[str] = [
        "initial",
        "format_correction",
        "evidence_correction",
    ]

    @model_validator(mode="after")
    def _check_limits(self) -> "HvsRosterRequestPolicy":
        _validate_request_ladder(
            max_scientific_requests=self.max_scientific_requests,
            max_transport_retries_per_call=self.max_transport_retries_per_call,
            max_total_physical_requests=self.max_total_physical_requests,
            max_format_correction_rounds=self.max_format_correction_rounds,
        )
        return self
