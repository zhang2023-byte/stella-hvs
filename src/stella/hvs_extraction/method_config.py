"""Frozen method configuration for the hvs_candidate_extraction pipeline.

Structure only: every method-affecting value stays ``None`` until the user
approves the concrete model routes, sampling settings, and context budgets.
``assert_frozen`` keeps unfrozen placeholder configs away from real model
requests.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from stella.lit.extraction.hashing import canonical_sha256
from stella.lit.schema_models import StrictModel
from stella.lit.extraction.bounded_call import MAX_TRANSPORT_ATTEMPTS
from stella.lit.extraction.method import (  # noqa: F401
    HvsComponentHashes,
    HvsContextBudget,
    HvsModelRoute,
    HvsRosterRequestPolicy,
    _validate_request_ladder,
)


PIPELINE_NAME = "hvs_candidate_extraction"
ROSTER_THINKING_TYPES = frozenset({"enabled", "disabled"})
ROSTER_REASONING_EFFORTS = frozenset(
    {"max", "xhigh", "high", "medium", "low", "minimal", "none"}
)
CORE_FIELD_REASONING_EFFORTS = ROSTER_REASONING_EFFORTS
CORE_FIELD_THINKING_TYPES = ROSTER_THINKING_TYPES
# json_object stays scoped to the roster extractor; the field stage is
# tool_submission only (field_stage rejects other modes).
ROSTER_STRUCTURED_OUTPUT_MODES = frozenset({"tool_submission", "json_object"})


class HvsExtractionRunConfigSchema(StrictModel):
    name: Literal["hvs_extraction.method_config"]
    version: Literal[1]








class HvsPeerConsistencyReviewPolicy(StrictModel):
    """Bounded deterministic post-field peer-consistency review.

    After a paper's candidate extractions finish, code compares delivered
    core fields across candidates of the same roster: when at least
    ``min_shared_peers`` candidates filled one field with an identical value,
    unit, limit kind, and direct-evidence locator (a shared group-level
    source), each remaining delivered candidate whose copy of that field is
    null gets one targeted re-examination request. The request has its own
    decoupled budget — one scientific slot plus a per-call transport-retry
    allowance under the ``max_physical_provider_requests`` physical ceiling —
    must only change the flagged field subtrees, and a failed review keeps
    the original delivery.
    """

    enabled: bool = False
    min_shared_peers: int = 2
    max_transport_retries_per_call: int = 2
    max_physical_provider_requests: int = 3

    @model_validator(mode="after")
    def _check_limits(self) -> "HvsPeerConsistencyReviewPolicy":
        if self.max_transport_retries_per_call < 0:
            raise ValueError("max_transport_retries_per_call must not be negative")
        if self.max_transport_retries_per_call > MAX_TRANSPORT_ATTEMPTS - 1:
            raise ValueError(
                "max_transport_retries_per_call cannot exceed the per-call "
                f"transport attempt bound ({MAX_TRANSPORT_ATTEMPTS - 1})"
            )
        if self.max_physical_provider_requests < 1 + self.max_transport_retries_per_call:
            raise ValueError(
                "max_physical_provider_requests must cover the one review "
                "request plus its per-call transport retries (at least "
                f"{1 + self.max_transport_retries_per_call})"
            )
        return self




class HvsFieldRequestPolicy(StrictModel):
    """Per-candidate field-stage request policy (fingerprinted).

    Scientific slots bound logical submissions: the initial request, each
    format-correction round, and the evidence correction. Automatic
    transport retries draw on a per-logical-call allowance — every logical
    call owns a full retry pool, and retries never consume a scientific
    slot; a non-retryable protocol rejection refunds its slot because the
    model never had a chance to answer. A hard physical ceiling bounds the
    sum over the whole candidate and is validated to never truncate the
    full correction ladder.
    """

    scope: Literal["per_candidate_field_stage"] = "per_candidate_field_stage"
    max_scientific_requests: int = 4
    max_transport_retries_per_call: int = 2
    max_total_physical_requests: int = 12
    max_format_correction_rounds: int = 2
    shared_across: list[str] = [
        "initial",
        "format_correction",
        "evidence_correction",
    ]
    peer_consistency_review: HvsPeerConsistencyReviewPolicy = (
        HvsPeerConsistencyReviewPolicy()
    )

    @model_validator(mode="after")
    def _check_limits(self) -> "HvsFieldRequestPolicy":
        _validate_request_ladder(
            max_scientific_requests=self.max_scientific_requests,
            max_transport_retries_per_call=self.max_transport_retries_per_call,
            max_total_physical_requests=self.max_total_physical_requests,
            max_format_correction_rounds=self.max_format_correction_rounds,
        )
        return self




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
    roster_request_policy: HvsRosterRequestPolicy = HvsRosterRequestPolicy()
    field_request_policy: HvsFieldRequestPolicy = HvsFieldRequestPolicy()
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


def default_hvs_extraction_method_config(
    workspace, *, roster_structured_output_mode: str = "tool_submission"
) -> HvsExtractionMethodConfig:
    """The user-approved frozen method values.

    The roster extractor is a single glm-5.2 call with
    thinking enabled, streaming transport (non-streaming long thinking
    generations hit the gateway idle timeout), temperature 0 / top_p 1,
    ``reserve_output`` 64000. Core-field extraction uses deepseek-v4-pro at
    temperature 0 / top_p 1.
    Both providers use a conservative 900K context limit against a nominal
    1M window (user-confirmed). ``seed_honored`` stays False because the
    authorized provider capability probe (2026-07-24) showed the route
    accepts but does not honor explicit seeds; no seed-level reproducibility
    is claimed.

    ``roster_structured_output_mode`` selects the roster submission contract.
    The default ``tool_submission`` keeps the typed-tool route;
    ``json_object`` renders the content-submission prompt variant with the
    submission schema embedded in the user message, so the frozen prompt
    template hash always matches the mode the runtime roster stage builds.
    """

    from stella.hvs_extraction.field_prompts import build_field_prompts
    from stella.hvs_extraction.field_schema import build_field_submission_schema
    from stella.hvs_extraction.roster_prompts import build_extractor_prompts
    from stella.hvs_extraction.submission_schema import build_roster_submission_schema
    from stella.lit.extraction_rules import rule_profile_sha256

    if roster_structured_output_mode not in ROSTER_STRUCTURED_OUTPUT_MODES:
        raise ValueError(
            "roster structured output mode must be one of: "
            + ", ".join(sorted(ROSTER_STRUCTURED_OUTPUT_MODES))
        )

    extractor = HvsModelRoute(
        provider="bigmodel",
        model="glm-5.2",
        structured_output_mode=roster_structured_output_mode,
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

    extractor_prompts = build_extractor_prompts(
        workspace,
        "<MANUSCRIPT>",
        mode=roster_structured_output_mode,
        schema=(
            build_roster_submission_schema(["<RUNTIME_TEX_PATH>"])
            if roster_structured_output_mode == "json_object"
            else None
        ),
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
        roster_request_policy=HvsRosterRequestPolicy(
            max_scientific_requests=3,
            max_transport_retries_per_call=2,
            max_total_physical_requests=10,
            max_format_correction_rounds=1,
            shared_across=[
                "initial",
                "format_correction",
                "evidence_correction",
            ],
        ),
        field_request_policy=HvsFieldRequestPolicy(
            max_scientific_requests=4,
            max_transport_retries_per_call=2,
            max_total_physical_requests=12,
            max_format_correction_rounds=2,
            shared_across=[
                "initial",
                "format_correction",
                "evidence_correction",
            ],
            peer_consistency_review=HvsPeerConsistencyReviewPolicy(
                enabled=False,
                min_shared_peers=2,
                max_transport_retries_per_call=2,
                max_physical_provider_requests=3,
            ),
        ),
        components=components,
    )
    config.assert_frozen()
    return config


def override_model_routes(
    config: HvsExtractionMethodConfig,
    *,
    roster_provider: str | None = None,
    roster_model: str | None = None,
    roster_thinking: str | None = None,
    roster_reasoning_effort: str | None = None,
    roster_provider_pin: str | None = None,
    core_field_provider: str | None = None,
    core_field_model: str | None = None,
    core_field_thinking: str | None = None,
    core_field_reasoning_effort: str | None = None,
    core_field_provider_pin: str | None = None,
    field_peer_consistency_review: bool | None = None,
) -> HvsExtractionMethodConfig:
    """Return a frozen config with explicit role-local route replacements.

    Roster thinking controls are frozen inside ``request_overrides`` so they
    participate in the method fingerprint. Reasoning effort is only accepted
    with explicitly enabled thinking; disabling thinking removes any previous
    effort override. The core-field route follows the same rules, except that
    a bare reasoning-effort override is allowed because the provider default
    is thinking enabled.

    ``roster_provider_pin`` / ``core_field_provider_pin`` freeze one gateway
    provider-routing tag into ``request_overrides["provider"]`` as
    ``{"only": [tag], "allow_fallbacks": False}``, so every physical request
    is served only by that gateway endpoint instead of the gateway's default
    price-first multi-provider routing. The pin participates in the method
    fingerprint like every other request override.

    ``field_peer_consistency_review`` toggles the bounded deterministic
    post-field review inside the fingerprinted ``field_request_policy``.
    """

    if (
        roster_thinking is not None
        and roster_thinking not in ROSTER_THINKING_TYPES
    ):
        raise ValueError(
            "roster thinking must be one of: "
            + ", ".join(sorted(ROSTER_THINKING_TYPES))
        )
    if (
        roster_reasoning_effort is not None
        and roster_reasoning_effort not in ROSTER_REASONING_EFFORTS
    ):
        raise ValueError(
            "roster reasoning effort must be one of: "
            + ", ".join(sorted(ROSTER_REASONING_EFFORTS))
        )
    if (
        core_field_thinking is not None
        and core_field_thinking not in CORE_FIELD_THINKING_TYPES
    ):
        raise ValueError(
            "core-field thinking must be one of: "
            + ", ".join(sorted(CORE_FIELD_THINKING_TYPES))
        )
    if (
        core_field_reasoning_effort is not None
        and core_field_reasoning_effort not in CORE_FIELD_REASONING_EFFORTS
    ):
        raise ValueError(
            "core-field reasoning effort must be one of: "
            + ", ".join(sorted(CORE_FIELD_REASONING_EFFORTS))
        )
    if core_field_thinking == "disabled" and core_field_reasoning_effort is not None:
        raise ValueError(
            "core-field reasoning effort requires core-field thinking enabled"
        )

    roster_updates = {
        key: value
        for key, value in {
            "provider": roster_provider,
            "model": roster_model,
        }.items()
        if value is not None
    }
    provider_changed = (
        roster_provider is not None
        and roster_provider != config.roster_model.provider
    )
    request_overrides = (
        {} if provider_changed else dict(config.roster_model.request_overrides)
    )
    if roster_thinking is not None:
        request_overrides["thinking"] = {"type": roster_thinking}
        if roster_thinking == "disabled":
            request_overrides.pop("reasoning_effort", None)
    if roster_reasoning_effort is not None:
        thinking = request_overrides.get("thinking")
        if not isinstance(thinking, dict) or thinking.get("type") != "enabled":
            raise ValueError(
                "roster reasoning effort requires roster thinking enabled"
            )
        request_overrides["reasoning_effort"] = roster_reasoning_effort
    if roster_provider_pin is not None:
        tag = str(roster_provider_pin).strip()
        if not tag:
            raise ValueError("roster provider pin must be a non-empty gateway tag")
        request_overrides["provider"] = {"only": [tag], "allow_fallbacks": False}
    if (
        provider_changed
        or roster_thinking is not None
        or roster_reasoning_effort is not None
        or roster_provider_pin is not None
    ):
        roster_updates["request_overrides"] = request_overrides
    field_updates: dict[str, Any] = {
        key: value
        for key, value in {
            "provider": core_field_provider,
            "model": core_field_model,
        }.items()
        if value is not None
    }
    field_provider_changed = (
        core_field_provider is not None
        and core_field_provider != config.core_field_model.provider
    )
    field_request_overrides = (
        {} if field_provider_changed else dict(config.core_field_model.request_overrides)
    )
    if core_field_thinking is not None:
        field_request_overrides["thinking"] = {"type": core_field_thinking}
        if core_field_thinking == "disabled":
            field_request_overrides.pop("reasoning_effort", None)
    if core_field_reasoning_effort is not None:
        field_request_overrides["reasoning_effort"] = core_field_reasoning_effort
    if core_field_provider_pin is not None:
        tag = str(core_field_provider_pin).strip()
        if not tag:
            raise ValueError(
                "core-field provider pin must be a non-empty gateway tag"
            )
        field_request_overrides["provider"] = {
            "only": [tag],
            "allow_fallbacks": False,
        }
    if (
        field_provider_changed
        or core_field_thinking is not None
        or core_field_reasoning_effort is not None
        or core_field_provider_pin is not None
    ):
        field_updates["request_overrides"] = field_request_overrides
    policy_updates: dict[str, Any] = {}
    if field_peer_consistency_review is not None:
        policy_updates["peer_consistency_review"] = (
            config.field_request_policy.peer_consistency_review.model_copy(
                update={"enabled": field_peer_consistency_review}
            )
        )
    policy = (
        config.field_request_policy.model_copy(update=policy_updates)
        if policy_updates
        else config.field_request_policy
    )
    updated = config.model_copy(
        update={
            "roster_model": config.roster_model.model_copy(
                update=roster_updates
            ),
            "core_field_model": config.core_field_model.model_copy(
                update=field_updates
            ),
            "field_request_policy": policy,
        }
    )
    updated.assert_frozen()
    return updated
