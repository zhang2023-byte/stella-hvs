"""Bounded model-call machinery: transport, format, and evidence correction.

Error classes stay mutually distinct (D017): transport failures (D020),
submission-format failures (D018, at most one correction), and
evidence-validation failures (D019, at most one drift-guarded correction).
Nothing here extracts JSON from assistant prose, adds missing fields, deletes
unexpected fields, or coerces model values (D017 no_silent_salvage).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from stella.benchmark.scratch.schema_check import SchemaIssue, collect_schema_errors
from stella.lit.llm_batch import LLMTransportError

OK = "ok"
TRANSPORT_FAILURE = "transport_failure"
REQUEST_REJECTED = "request_rejected"
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


def extract_tool_payload(response: dict[str, Any], tool_name: str) -> dict[str, Any]:
    """Extract exactly one target-function call without any salvage."""

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
    except json.JSONDecodeError as exc:
        raise SubmissionProtocolError(
            MALFORMED_ARGUMENTS, f"malformed tool arguments: {exc}", raw_arguments=raw
        ) from exc
    if not isinstance(payload, dict):
        raise SubmissionProtocolError(
            ARGUMENTS_NOT_OBJECT,
            f"tool arguments must be a JSON object, got {type(payload).__name__}",
            raw_arguments=raw,
        )
    return payload


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
) -> CallOutcome:
    """Run one logical model call under the D020 transport budget."""

    attempts: list[dict[str, Any]] = []
    response: dict[str, Any] | None = None
    for index in range(1, max_transport_attempts + 1):
        record: dict[str, Any] = {
            "index": index,
            "kind": "initial" if index == 1 else "transport_retry",
            "started_at": time.time(),
        }
        try:
            response = transport(**transport_kwargs)
            record["outcome"] = "response_received"
            attempts.append(record)
            break
        except LLMTransportError as exc:
            record.update(
                {
                    "outcome": "transport_error",
                    "error_class": exc.category,
                    "http_status": exc.http_status,
                    "retryable": exc.automatic_retryable,
                }
            )
            attempts.append(record)
            retry = exc.automatic_retryable and index < max_transport_attempts
            record["retry_decision"] = "retry" if retry else "stop"
            if retry:
                sleep(_retry_delay(index))
                continue
            status = TRANSPORT_FAILURE if exc.automatic_retryable else REQUEST_REJECTED
            return CallOutcome(
                status=status, transport_error=exc, attempts=attempts
            )
        except Exception as exc:  # noqa: BLE001 - unexpected transport defect
            record.update(
                {"outcome": "transport_error", "error_class": type(exc).__name__}
            )
            attempts.append(record)
            return CallOutcome(
                status=TRANSPORT_FAILURE,
                other_error=f"{type(exc).__name__}: {exc}",
                attempts=attempts,
            )

    assert response is not None
    try:
        payload = extract_tool_payload(response, tool_name)
    except SubmissionProtocolError as exc:
        return CallOutcome(
            status=SUBMISSION_FORMAT_FAILURE,
            response=response,
            protocol_error=exc,
            attempts=attempts,
        )
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


def build_format_correction_message(outcome: CallOutcome, tool_name: str) -> str:
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
        f"Submit the complete corrected submission once by calling {tool_name} "
        "exactly once, with arguments that satisfy the function parameter "
        "schema. Do not change your scientific decisions merely to repair "
        "structure."
    )
    return "\n".join(parts)


def build_evidence_correction_message(
    issues: list[Any],
    previous_payload: dict[str, Any],
    tool_name: str,
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
            f"Submit the complete corrected submission once by calling "
            f"{tool_name} exactly once. Change only the fields named by the "
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
    response: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    usages: list[dict[str, Any]] = field(default_factory=list)


def execute_with_format_correction(
    *,
    transport: Transport,
    transport_kwargs: dict[str, Any],
    tool_name: str,
    schema: dict[str, Any],
    messages: list[dict[str, str]],
    sleep: Callable[[float], None] = time.sleep,
) -> BoundedSubmission:
    """D018: one initial submission and at most one format correction."""

    first = execute_model_call(
        transport=transport,
        transport_kwargs={**transport_kwargs, "messages": messages},
        tool_name=tool_name,
        schema=schema,
        sleep=sleep,
    )
    if first.status != SUBMISSION_FORMAT_FAILURE:
        return BoundedSubmission(
            status=first.status,
            payload=first.payload,
            attempts=first.attempts,
            transport_error=first.transport_error.to_dict()
            if first.transport_error
            else None,
            response=first.response,
            usage=first.usage,
            usages=[first.usage] if first.usage else [],
        )

    correction_text = build_format_correction_message(first, tool_name)
    second = execute_model_call(
        transport=transport,
        transport_kwargs={
            **transport_kwargs,
            "messages": [*messages, {"role": "user", "content": correction_text}],
        },
        tool_name=tool_name,
        schema=schema,
        sleep=sleep,
    )
    attempts = [
        *first.attempts,
        *[{**record, "kind": "format_correction"} for record in second.attempts],
    ]
    usages = [usage for usage in (first.usage, second.usage) if usage]
    if second.status == OK:
        return BoundedSubmission(
            status=OK,
            payload=second.payload,
            attempts=attempts,
            response=second.response,
            usage=second.usage,
            usages=usages,
        )
    if second.status in (TRANSPORT_FAILURE, REQUEST_REJECTED):
        return BoundedSubmission(
            status=second.status,
            attempts=attempts,
            transport_error=second.transport_error.to_dict()
            if second.transport_error
            else None,
            usages=usages,
        )
    return BoundedSubmission(
        status=SUBMISSION_FORMAT_FAILURE,
        attempts=attempts,
        initial_errors=_error_lines(first),
        correction_errors=_error_lines(second),
        usages=usages,
    )


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def drift_violations(
    previous: dict[str, Any],
    corrected: dict[str, Any],
    allowed_roots: set[str],
) -> list[str]:
    """D019/D046 drift guard: nothing outside the error subtrees may change."""

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
            if len(old) != len(new):
                violations.append(f"{path} changed length")
                return
            for index, (old_item, new_item) in enumerate(zip(old, new)):
                walk(old_item, new_item, f"{path}[{index}]")
        elif canonical_json(old) != canonical_json(new):
            violations.append(f"{path} changed outside the permitted correction scope")

    for key in ("candidates", "reviewed_exclusions"):
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
    usage: dict[str, Any] | None = None
    usages: list[dict[str, Any]] = field(default_factory=list)


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
) -> EvidenceCorrectionResult:
    """D019: one drift-guarded correction for deterministic evidence errors."""

    if allowed_roots_fn is None:
        allowed_roots = {issue.path for issue in issues}
    else:
        allowed_roots = allowed_roots_fn(issues)
    correction_text = build_evidence_correction_message(
        issues, previous_payload, tool_name
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
    )
    attempts = [{**record, "kind": "evidence_correction"} for record in second.attempts]
    initial_errors = [issue.render() for issue in issues]
    usages = [second.usage] if second.usage else []
    if second.status != OK:
        if second.status in (TRANSPORT_FAILURE, REQUEST_REJECTED):
            return EvidenceCorrectionResult(
                status=second.status,
                attempts=attempts,
                transport_error=second.transport_error.to_dict()
                if second.transport_error
                else None,
                usages=usages,
            )
        return EvidenceCorrectionResult(
            status=EVIDENCE_VALIDATION_FAILURE,
            attempts=attempts,
            initial_errors=initial_errors,
            correction_errors=_error_lines(second),
            usages=usages,
        )
    assert second.payload is not None
    new_issues = validate_fn(second.payload)
    if new_issues:
        return EvidenceCorrectionResult(
            status=EVIDENCE_VALIDATION_FAILURE,
            attempts=attempts,
            initial_errors=initial_errors,
            correction_errors=[issue.render() for issue in new_issues],
            usages=usages,
        )
    violations = drift_violations(previous_payload, second.payload, allowed_roots)
    if violations:
        return EvidenceCorrectionResult(
            status=CORRECTION_DRIFT,
            attempts=attempts,
            initial_errors=initial_errors,
            unexpected_changes=violations,
            usages=usages,
        )
    return EvidenceCorrectionResult(
        status=OK,
        payload=second.payload,
        attempts=attempts,
        usage=second.usage,
        usages=usages,
    )
