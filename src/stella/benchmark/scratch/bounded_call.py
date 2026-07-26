"""Bounded model-call machinery: transport, format, and evidence correction.

Error classes stay mutually distinct (D017): transport failures (D020),
submission-format failures (D018, at most one correction), and
evidence-validation failures (D019, at most one drift-guarded correction).
Nothing here extracts JSON from assistant prose, adds missing fields, deletes
unexpected fields, or coerces model values (D017 no_silent_salvage). The one
narrow exception is D055: when the arguments string is one complete JSON
document followed by provider-appended trailing bytes, the first document is
accepted and the tail is discarded with an auditable attempt-record marker.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from stella.benchmark.scratch.schema_check import SchemaIssue, collect_schema_errors
from stella.lit.llm_batch import LLMTransportError

OK = "ok"
TRANSPORT_FAILURE = "transport_failure"
REQUEST_REJECTED = "request_rejected"
REQUEST_BUDGET_EXHAUSTED = "request_budget_exhausted"
INPUT_TOO_LARGE = "input_too_large"
SUBMISSION_FORMAT_FAILURE = "submission_format_failure"
EVIDENCE_VALIDATION_FAILURE = "evidence_validation_failure"
CORRECTION_DRIFT = "correction_drift"

MISSING_SUBMISSION_CALL = "missing_submission_call"
WRONG_FUNCTION = "wrong_function"
MULTIPLE_SUBMISSION_CALLS = "multiple_submission_calls"
MALFORMED_ARGUMENTS = "malformed_arguments"
ARGUMENTS_NOT_OBJECT = "arguments_not_object"

MAX_TRANSPORT_ATTEMPTS = 3  # D020: initial attempt + two automatic retries

Transport = Callable[..., dict[str, Any]]
Progress = Callable[..., None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _emit(
    progress: Progress | None,
    event: str,
    context: dict[str, Any] | None,
    **details: Any,
) -> None:
    if progress is not None:
        progress(event, **(context or {}), **details)


@dataclass
class ProviderRequestBudget:
    """Shared physical-provider-request allowance for one field candidate."""

    limit: int = 3
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(self.limit - self.used, 0)

    def consume(self) -> int | None:
        if self.remaining <= 0:
            return None
        self.used += 1
        return self.used


def serialized_request_size(
    *,
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
    tool_name: str,
    mode: str,
) -> dict[str, int]:
    """Exact serialized size plus the conservative scratch token estimate."""

    serialized = json.dumps(
        {
            "messages": messages,
            "schema": schema,
            "submission_name": tool_name,
            "structured_output_mode": mode,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    raw = serialized.encode("utf-8")
    return {
        "characters": len(serialized),
        "bytes": len(raw),
        "estimated_tokens": math.ceil(len(raw) / 3.0),
    }


class SubmissionProtocolError(ValueError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        raw_arguments: str | None = None,
        parsed_arguments: dict[str, Any] | None = None,
        function_names: list[str] | None = None,
    ) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.raw_arguments = raw_arguments
        self.parsed_arguments = parsed_arguments
        self.function_names = function_names or []


def _recover_trailing_content(
    raw: str, error: json.JSONDecodeError
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """D055: accept one complete JSON document before provider-appended bytes.

    Only a strict "Extra data" failure with a recoverable first JSON object
    qualifies; every other shape stays a D017 malformed-arguments failure.
    """

    if "Extra data" not in str(error):
        return None, None
    start = len(raw) - len(raw.lstrip())
    try:
        document, end = json.JSONDecoder().raw_decode(raw, start)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(document, dict) or end >= len(raw):
        return None, None
    tail = raw[end:]
    return document, {
        "kind": "trailing_content_after_json_document",
        "tail_length": len(tail),
        "tail_sha256": hashlib.sha256(tail.encode("utf-8")).hexdigest(),
    }


def extract_tool_payload(
    response: dict[str, Any], tool_name: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Extract exactly one target-function call without any salvage.

    Returns the payload and an optional D055 salvage record describing any
    discarded provider-appended trailing bytes.
    """

    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    calls = message.get("tool_calls") or []
    names = [
        str((call.get("function") or {}).get("name") or "")
        for call in calls
        if isinstance(call, dict)
    ]
    target_calls = [
        call for call in calls if (call.get("function") or {}).get("name") == tool_name
    ]
    if not names:
        raise SubmissionProtocolError(
            MISSING_SUBMISSION_CALL,
            f"response contains no tool call; expected exactly one {tool_name} call",
        )
    if not target_calls:
        raise SubmissionProtocolError(
            WRONG_FUNCTION,
            f"expected tool {tool_name!r}, got {names!r}",
            function_names=names,
        )
    if len(target_calls) > 1:
        raise SubmissionProtocolError(
            MULTIPLE_SUBMISSION_CALLS,
            f"expected exactly one {tool_name} call, got {len(target_calls)}",
            function_names=names,
        )
    raw = (target_calls[0].get("function") or {}).get("arguments")
    if not isinstance(raw, str):
        raise SubmissionProtocolError(
            MALFORMED_ARGUMENTS, "tool arguments are not a JSON string"
        )
    try:
        payload = json.loads(raw)
        salvage = None
    except json.JSONDecodeError as exc:
        payload, salvage = _recover_trailing_content(raw, exc)
        if payload is None:
            raise SubmissionProtocolError(
                MALFORMED_ARGUMENTS, f"malformed tool arguments: {exc}", raw_arguments=raw
            ) from exc
    if not isinstance(payload, dict):
        raise SubmissionProtocolError(
            ARGUMENTS_NOT_OBJECT,
            f"tool arguments must be a JSON object, got {type(payload).__name__}",
            raw_arguments=raw,
        )
    return payload, salvage


def extract_content_payload(
    response: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """D057 json_object mode: extract the single JSON object from content.

    Same discipline as tool parsing: no fences, no substring extraction; D055
    trailing-content recovery applies identically.
    """

    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    raw = message.get("content")
    if not isinstance(raw, str) or not raw.strip():
        raise SubmissionProtocolError(
            MISSING_SUBMISSION_CALL,
            "response contains no JSON content; expected exactly one JSON object",
        )
    try:
        payload = json.loads(raw)
        salvage = None
    except json.JSONDecodeError as exc:
        payload, salvage = _recover_trailing_content(raw, exc)
        if payload is None:
            raise SubmissionProtocolError(
                MALFORMED_ARGUMENTS, f"malformed JSON content: {exc}", raw_arguments=raw
            ) from exc
    if not isinstance(payload, dict):
        raise SubmissionProtocolError(
            ARGUMENTS_NOT_OBJECT,
            f"JSON content must be an object, got {type(payload).__name__}",
            raw_arguments=raw,
        )
    return payload, salvage


@dataclass
class CallOutcome:
    status: str
    payload: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    schema_issues: list[SchemaIssue] = field(default_factory=list)
    protocol_error: SubmissionProtocolError | None = None
    transport_error: LLMTransportError | None = None
    other_error: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)

    @property
    def usage(self) -> dict[str, Any] | None:
        """Token usage of the received response, if any (cost accounting)."""

        return (self.response or {}).get("usage")


def _retry_delay(attempt: int) -> float:
    # Increasing delay with bounded deterministic jitter (D020).
    return min(2.0**attempt, 8.0) * (1.0 + ((attempt * 37) % 10) / 40.0)


def execute_model_call(
    *,
    transport: Transport,
    transport_kwargs: dict[str, Any],
    tool_name: str,
    schema: dict[str, Any],
    sleep: Callable[[float], None] = time.sleep,
    max_transport_attempts: int = MAX_TRANSPORT_ATTEMPTS,
    mode: str = "tool_submission",
    request_budget: ProviderRequestBudget | None = None,
    input_token_budget: int | None = None,
    request_kind: str = "initial",
    progress: Progress | None = None,
    progress_context: dict[str, Any] | None = None,
) -> CallOutcome:
    """Run one logical model call under the D020 transport budget."""

    attempts: list[dict[str, Any]] = []
    response: dict[str, Any] | None = None
    request_size = serialized_request_size(
        messages=transport_kwargs.get("messages") or [],
        schema=schema,
        tool_name=tool_name,
        mode=mode,
    )
    if (
        input_token_budget is not None
        and request_size["estimated_tokens"] > input_token_budget
    ):
        _emit(
            progress,
            "api_request_blocked",
            progress_context,
            correction_type=request_kind,
            reason=INPUT_TOO_LARGE,
            estimated_tokens=request_size["estimated_tokens"],
        )
        return CallOutcome(
            status=INPUT_TOO_LARGE,
            other_error=(
                "serialized request is "
                f"{request_size['characters']} characters / "
                f"{request_size['bytes']} bytes / "
                f"{request_size['estimated_tokens']} estimated tokens, over "
                f"the input budget {input_token_budget}; no API request was made"
            ),
        )
    for index in range(1, max_transport_attempts + 1):
        physical_index = request_budget.consume() if request_budget else index
        if physical_index is None:
            _emit(
                progress,
                "api_request_blocked",
                progress_context,
                correction_type=request_kind,
                reason=REQUEST_BUDGET_EXHAUSTED,
            )
            return CallOutcome(
                status=REQUEST_BUDGET_EXHAUSTED,
                other_error="the shared three-request field budget is exhausted",
                attempts=attempts,
            )
        monotonic_started = time.monotonic()
        correction_type = request_kind if request_kind != "initial" else None
        record: dict[str, Any] = {
            "index": index,
            "physical_request_index": physical_index,
            "kind": "initial" if index == 1 else "transport_retry",
            "started_at": _utc_now(),
            "request_size": request_size,
        }
        _emit(
            progress,
            "api_attempt_start",
            progress_context,
            attempt=physical_index,
            transport_attempt=index,
            correction_type=correction_type,
        )
        try:
            response = transport(**transport_kwargs)
            record.update(
                {
                    "outcome": "response_received",
                    "transport_classification": "success",
                    "http_status": None,
                    "retry_decision": "stop",
                    "usage": response.get("usage"),
                }
            )
            record["finished_at"] = _utc_now()
            record["duration_ms"] = round(
                (time.monotonic() - monotonic_started) * 1000, 3
            )
            attempts.append(record)
            usage = response.get("usage") or {}
            _emit(
                progress,
                "api_attempt_end",
                progress_context,
                attempt=physical_index,
                correction_type=correction_type,
                outcome="response_received",
                duration_ms=record["duration_ms"],
                tokens=usage.get("total_tokens", 0),
            )
            break
        except LLMTransportError as exc:
            record.update(
                {
                    "outcome": "transport_error",
                    "error_class": exc.category,
                    "transport_classification": exc.category,
                    "http_status": exc.http_status,
                    "retryable": exc.automatic_retryable,
                    "usage": None,
                }
            )
            record["finished_at"] = _utc_now()
            record["duration_ms"] = round(
                (time.monotonic() - monotonic_started) * 1000, 3
            )
            attempts.append(record)
            retry = (
                exc.automatic_retryable
                and index < max_transport_attempts
                and (request_budget is None or request_budget.remaining > 0)
            )
            record["retry_decision"] = "retry" if retry else "stop"
            _emit(
                progress,
                "api_attempt_end",
                progress_context,
                attempt=physical_index,
                correction_type=correction_type,
                outcome="transport_error",
                transport_classification=exc.category,
                http_status=exc.http_status,
                retry_decision=record["retry_decision"],
                duration_ms=record["duration_ms"],
                tokens=0,
            )
            if retry:
                _emit(
                    progress,
                    "api_retry",
                    progress_context,
                    after_attempt=physical_index,
                    correction_type=correction_type,
                    transport_classification=exc.category,
                )
                sleep(_retry_delay(index))
                continue
            if (
                exc.automatic_retryable
                and request_budget is not None
                and request_budget.remaining == 0
            ):
                record["retry_decision"] = "stop_request_budget_exhausted"
                return CallOutcome(
                    status=REQUEST_BUDGET_EXHAUSTED,
                    transport_error=exc,
                    attempts=attempts,
                )
            status = TRANSPORT_FAILURE if exc.automatic_retryable else REQUEST_REJECTED
            return CallOutcome(
                status=status, transport_error=exc, attempts=attempts
            )
        except Exception as exc:  # noqa: BLE001 - unexpected transport defect
            record.update(
                {
                    "outcome": "transport_error",
                    "error_class": type(exc).__name__,
                    "transport_classification": "unexpected_exception",
                    "http_status": None,
                    "retryable": False,
                    "retry_decision": "stop",
                    "usage": None,
                }
            )
            record["finished_at"] = _utc_now()
            record["duration_ms"] = round(
                (time.monotonic() - monotonic_started) * 1000, 3
            )
            attempts.append(record)
            _emit(
                progress,
                "api_attempt_end",
                progress_context,
                attempt=physical_index,
                correction_type=correction_type,
                outcome="transport_error",
                transport_classification="unexpected_exception",
                retry_decision="stop",
                duration_ms=record["duration_ms"],
                tokens=0,
            )
            return CallOutcome(
                status=TRANSPORT_FAILURE,
                other_error=f"{type(exc).__name__}: {exc}",
                attempts=attempts,
            )

    assert response is not None
    try:
        if mode == "json_object":
            payload, salvage = extract_content_payload(response)
        else:
            payload, salvage = extract_tool_payload(response, tool_name)
    except SubmissionProtocolError as exc:
        return CallOutcome(
            status=SUBMISSION_FORMAT_FAILURE,
            response=response,
            protocol_error=exc,
            attempts=attempts,
        )
    if salvage:
        attempts[-1]["salvage"] = salvage
    issues = collect_schema_errors(payload, schema)
    if issues:
        return CallOutcome(
            status=SUBMISSION_FORMAT_FAILURE,
            payload=payload,
            response=response,
            schema_issues=issues,
            attempts=attempts,
        )
    return CallOutcome(
        status=OK, payload=payload, response=response, attempts=attempts
    )


def _error_lines(outcome: CallOutcome) -> list[str]:
    if outcome.protocol_error is not None:
        return [f"- {outcome.protocol_error.code}: {outcome.protocol_error.detail}"]
    return [f"- {issue.render()}" for issue in outcome.schema_issues]


def _previous_arguments_replay(outcome: CallOutcome) -> str:
    error = outcome.protocol_error
    if error is None and outcome.payload is not None:
        return (
            "Your previous function arguments were:\n"
            + json.dumps(outcome.payload, ensure_ascii=False, indent=2)
        )
    if error is None:
        return ""
    if error.code in (MALFORMED_ARGUMENTS, ARGUMENTS_NOT_OBJECT) and error.raw_arguments:
        return (
            "Your previous function arguments were rejected unparseable:\n"
            + error.raw_arguments
        )
    if error.code == MULTIPLE_SUBMISSION_CALLS:
        counts: dict[str, int] = {}
        for name in error.function_names:
            counts[name] = counts.get(name, 0) + 1
        return (
            "Your previous response made these function calls (name: count): "
            + json.dumps(counts, ensure_ascii=False)
        )
    return (
        "Your previous response did not make the required submission function "
        "call; no assistant text is replayed here."
    )


def _submission_action_sentence(tool_name: str, mode: str) -> str:
    if mode == "json_object":
        return (
            "as exactly one JSON object in your response content, with "
            "properties that satisfy the output contract JSON schema"
        )
    return (
        f"by calling {tool_name} exactly once, with arguments that satisfy "
        "the function parameter schema"
    )


def build_format_correction_message(
    outcome: CallOutcome, tool_name: str, *, mode: str = "tool_submission"
) -> str:
    """D018 correction context: exact errors, replay per policy, resubmit once."""

    parts = [
        "===== SUBMISSION CORRECTION =====",
        "",
        "Your previous submission did not satisfy the machine contract.",
        "",
        "Errors:",
        *_error_lines(outcome),
        "",
    ]
    replay = _previous_arguments_replay(outcome)
    if replay:
        parts.extend([replay, ""])
    parts.append(
        "Submit the complete corrected submission once "
        + _submission_action_sentence(tool_name, mode)
        + ". Do not change your scientific decisions merely to repair "
        "structure."
    )
    return "\n".join(parts)


def build_evidence_correction_message(
    issues: list[Any],
    previous_payload: dict[str, Any],
    tool_name: str,
    *,
    mode: str = "tool_submission",
) -> str:
    """D019/D046 correction context: previous valid args plus exact errors."""

    lines = [
        "===== EVIDENCE CORRECTION =====",
        "",
        "Your previous submission was structurally valid, but deterministic "
        "source checks failed.",
        "",
        "Errors:",
    ]
    lines.extend(f"- {issue.render()}" for issue in issues)
    lines.extend(
        [
            "",
            "Your previous function arguments were:",
            json.dumps(previous_payload, ensure_ascii=False, indent=2),
            "",
            "Submit the complete corrected submission once "
            + _submission_action_sentence(tool_name, mode)
            + ". Change only the fields named by the "
            "errors above; preserve every unaffected value and array order.",
        ]
    )
    return "\n".join(lines)


@dataclass
class BoundedSubmission:
    """Result of one initial call plus at most one format correction (D018)."""

    status: str
    payload: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    initial_errors: list[str] = field(default_factory=list)
    correction_errors: list[str] = field(default_factory=list)
    transport_error: dict[str, Any] | None = None
    other_error: str = ""
    response: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    usages: list[dict[str, Any]] = field(default_factory=list)
    repair_history: list[dict[str, Any]] = field(default_factory=list)


def execute_with_format_correction(
    *,
    transport: Transport,
    transport_kwargs: dict[str, Any],
    tool_name: str,
    schema: dict[str, Any],
    messages: list[dict[str, str]],
    sleep: Callable[[float], None] = time.sleep,
    mode: str = "tool_submission",
    request_budget: ProviderRequestBudget | None = None,
    input_token_budget: int | None = None,
    progress: Progress | None = None,
    progress_context: dict[str, Any] | None = None,
) -> BoundedSubmission:
    """D018: one initial submission and at most one format correction."""

    first = execute_model_call(
        transport=transport,
        transport_kwargs={**transport_kwargs, "messages": messages},
        tool_name=tool_name,
        schema=schema,
        sleep=sleep,
        mode=mode,
        request_budget=request_budget,
        input_token_budget=input_token_budget,
        request_kind="initial",
        progress=progress,
        progress_context=progress_context,
    )
    if first.status != SUBMISSION_FORMAT_FAILURE:
        return BoundedSubmission(
            status=first.status,
            payload=first.payload,
            attempts=first.attempts,
            transport_error=first.transport_error.to_dict()
            if first.transport_error
            else None,
            other_error=first.other_error,
            response=first.response,
            usage=first.usage,
            usages=[first.usage] if first.usage else [],
        )

    correction_text = build_format_correction_message(first, tool_name, mode=mode)
    second = execute_model_call(
        transport=transport,
        transport_kwargs={
            **transport_kwargs,
            "messages": [*messages, {"role": "user", "content": correction_text}],
        },
        tool_name=tool_name,
        schema=schema,
        sleep=sleep,
        mode=mode,
        request_budget=request_budget,
        input_token_budget=input_token_budget,
        request_kind="format_correction",
        progress=progress,
        progress_context=progress_context,
    )
    attempts = [
        *first.attempts,
        *[
            {
                **record,
                "transport_attempt_kind": record["kind"],
                "kind": "format_correction",
            }
            for record in second.attempts
        ],
    ]
    usages = [usage for usage in (first.usage, second.usage) if usage]
    repair_history = [
        {
            "type": "format_correction",
            "trigger_errors": _error_lines(first),
            "physical_requests_consumed": len(second.attempts),
            "final_status": second.status,
            "final_result": "accepted" if second.status == OK else "failed",
            "usage": [usage for usage in (second.usage,) if usage],
        }
    ]
    if second.status == OK:
        return BoundedSubmission(
            status=OK,
            payload=second.payload,
            attempts=attempts,
            response=second.response,
            usage=second.usage,
            usages=usages,
            repair_history=repair_history,
        )
    if second.status in (
        TRANSPORT_FAILURE,
        REQUEST_REJECTED,
        REQUEST_BUDGET_EXHAUSTED,
        INPUT_TOO_LARGE,
    ):
        return BoundedSubmission(
            status=second.status,
            attempts=attempts,
            transport_error=second.transport_error.to_dict()
            if second.transport_error
            else None,
            other_error=second.other_error,
            usages=usages,
            initial_errors=_error_lines(first),
            repair_history=repair_history,
        )
    return BoundedSubmission(
        status=SUBMISSION_FORMAT_FAILURE,
        attempts=attempts,
        initial_errors=_error_lines(first),
        correction_errors=_error_lines(second),
        usages=usages,
        repair_history=repair_history,
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _allowed_element_indices(allowed_roots: set[str], path: str) -> set[int]:
    """Numeric child indices of ``path`` covered by allowed roots (D056)."""

    prefix = f"{path}["
    indices: set[int] = set()
    for root in allowed_roots:
        if not root.startswith(prefix):
            continue
        head = root[len(prefix):].split("]", 1)[0]
        if head.isdigit():
            indices.add(int(head))
    return indices


def drift_violations(
    previous: dict[str, Any],
    corrected: dict[str, Any],
    allowed_roots: set[str],
) -> list[str]:
    """D019/D046 drift guard: nothing outside the error subtrees may change.

    D056 relaxation: an array may only shrink, and only by deleting elements
    covered by allowed roots; retained elements must stay byte-identical in
    their original order, compared under their original indices.
    """

    violations: list[str] = []
    if set(previous) != set(corrected):
        violations.append("top-level keys changed")

    def walk(old: Any, new: Any, path: str) -> None:
        if path in allowed_roots:
            return
        if type(old) is not type(new) and not (
            isinstance(old, (int, float))
            and isinstance(new, (int, float))
            and not isinstance(old, bool)
            and not isinstance(new, bool)
        ):
            violations.append(f"{path} changed type")
            return
        if isinstance(old, dict):
            if set(old) != set(new):
                violations.append(f"{path} changed keys")
                return
            for key in old:
                walk(old[key], new[key], f"{path}.{key}")
        elif isinstance(old, list):
            if len(new) > len(old):
                violations.append(f"{path} changed length")
                return
            if len(old) != len(new):
                allowed = _allowed_element_indices(allowed_roots, path)
                retained = [item for index, item in enumerate(old) if index not in allowed]
                if len(retained) != len(new):
                    violations.append(f"{path} changed length")
                    return
                old_index = 0
                for new_item in new:
                    while old_index in allowed:
                        old_index += 1
                    walk(old[old_index], new_item, f"{path}[{old_index}]")
                    old_index += 1
                return
            for index, (old_item, new_item) in enumerate(zip(old, new)):
                walk(old_item, new_item, f"{path}[{index}]")
        elif canonical_json(old) != canonical_json(new):
            violations.append(f"{path} changed outside the permitted correction scope")

    for key in ("candidates", "reviewed_exclusions", "range_groups"):
        if key in previous and key in corrected and len(previous[key]) != len(corrected[key]):
            violations.append(
                f"{key} count changed from {len(previous[key])} to {len(corrected[key])}"
            )
    for key in sorted(set(previous) & set(corrected)):
        walk(previous[key], corrected[key], f"$.{key}")
    return violations


@dataclass
class EvidenceCorrectionResult:
    status: str
    payload: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    initial_errors: list[str] = field(default_factory=list)
    correction_errors: list[str] = field(default_factory=list)
    unexpected_changes: list[str] = field(default_factory=list)
    transport_error: dict[str, Any] | None = None
    other_error: str = ""
    usage: dict[str, Any] | None = None
    usages: list[dict[str, Any]] = field(default_factory=list)
    repair_history: list[dict[str, Any]] = field(default_factory=list)


def execute_with_evidence_correction(
    *,
    transport: Transport,
    transport_kwargs: dict[str, Any],
    tool_name: str,
    schema: dict[str, Any],
    messages: list[dict[str, str]],
    previous_payload: dict[str, Any],
    issues: list[Any],
    validate_fn: Callable[[dict[str, Any]], list[Any]],
    sleep: Callable[[float], None] = time.sleep,
    allowed_roots_fn: Callable[[list[Any]], set[str]] | None = None,
    mode: str = "tool_submission",
    request_budget: ProviderRequestBudget | None = None,
    input_token_budget: int | None = None,
    progress: Progress | None = None,
    progress_context: dict[str, Any] | None = None,
) -> EvidenceCorrectionResult:
    """D019: one drift-guarded correction for deterministic evidence errors."""

    if allowed_roots_fn is None:
        allowed_roots = {issue.path for issue in issues}
    else:
        allowed_roots = allowed_roots_fn(issues)
    correction_text = build_evidence_correction_message(
        issues, previous_payload, tool_name, mode=mode
    )
    second = execute_model_call(
        transport=transport,
        transport_kwargs={
            **transport_kwargs,
            "messages": [*messages, {"role": "user", "content": correction_text}],
        },
        tool_name=tool_name,
        schema=schema,
        sleep=sleep,
        mode=mode,
        request_budget=request_budget,
        input_token_budget=input_token_budget,
        request_kind="evidence_correction",
        progress=progress,
        progress_context=progress_context,
    )
    attempts = [
        {
            **record,
            "transport_attempt_kind": record["kind"],
            "kind": "evidence_correction",
        }
        for record in second.attempts
    ]
    initial_errors = [issue.render() for issue in issues]
    usages = [second.usage] if second.usage else []
    repair_history = [
        {
            "type": "evidence_correction",
            "trigger_errors": initial_errors,
            "physical_requests_consumed": len(second.attempts),
            "final_status": second.status,
            "final_result": "accepted" if second.status == OK else "failed",
            "usage": usages,
        }
    ]
    if second.status != OK:
        if second.status in (
            TRANSPORT_FAILURE,
            REQUEST_REJECTED,
            REQUEST_BUDGET_EXHAUSTED,
            INPUT_TOO_LARGE,
        ):
            return EvidenceCorrectionResult(
                status=second.status,
                attempts=attempts,
                transport_error=second.transport_error.to_dict()
                if second.transport_error
                else None,
                other_error=second.other_error,
                usages=usages,
                initial_errors=initial_errors,
                repair_history=repair_history,
            )
        return EvidenceCorrectionResult(
            status=EVIDENCE_VALIDATION_FAILURE,
            attempts=attempts,
            initial_errors=initial_errors,
            correction_errors=_error_lines(second),
            usages=usages,
            repair_history=repair_history,
        )
    assert second.payload is not None
    new_issues = validate_fn(second.payload)
    if new_issues:
        repair_history[0].update(
            {
                "final_status": EVIDENCE_VALIDATION_FAILURE,
                "final_result": "failed",
                "result_errors": [issue.render() for issue in new_issues],
            }
        )
        return EvidenceCorrectionResult(
            status=EVIDENCE_VALIDATION_FAILURE,
            attempts=attempts,
            initial_errors=initial_errors,
            correction_errors=[issue.render() for issue in new_issues],
            usages=usages,
            repair_history=repair_history,
        )
    violations = drift_violations(previous_payload, second.payload, allowed_roots)
    if violations:
        repair_history[0].update(
            {
                "final_status": CORRECTION_DRIFT,
                "final_result": "failed",
                "result_errors": violations,
            }
        )
        return EvidenceCorrectionResult(
            status=CORRECTION_DRIFT,
            attempts=attempts,
            initial_errors=initial_errors,
            unexpected_changes=violations,
            usages=usages,
            repair_history=repair_history,
        )
    return EvidenceCorrectionResult(
        status=OK,
        payload=second.payload,
        attempts=attempts,
        usage=second.usage,
        usages=usages,
        repair_history=repair_history,
    )
