"""Immutable TokenDance price snapshots and reproducible API-cost estimates."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from stella.benchmark.campaign import sha256_file
from stella.benchmark.paths import validate_path_segment
from stella.benchmark.run_contract import canonical_sha256
from stella.schema_registry import require_schema, schema_ref

PRICE_SOURCE_URLS = {
    "TokenDance": "https://tokendance.space/models",
    "DeepSeek": "https://api-docs.deepseek.com/",
}
TIME_TIER_TIMEZONES = {"Asia/Shanghai"}
PEAK_WINDOW_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
TIME_TIER_BANDS = {"peak", "off_peak"}
COST_FORMULA_VERSION = "1.1.0"
MILLION = Decimal("1000000")
MONEY_QUANTUM = Decimal("0.000001")
DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def _decimal_string(value: Any, *, label: str) -> Decimal:
    if not isinstance(value, str) or DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a non-negative decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{label} is not a decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return parsed


def _iso_timestamp(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be an ISO-8601 timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    return value


def _source_route(
    route: dict[str, Any], *, label: str
) -> dict[str, Any]:
    source_route = route.get("source_route")
    if not isinstance(source_route, dict) or any(
        not isinstance(source_route.get(field), str)
        or not source_route[field].strip()
        for field in ("model_slug", "provider_slug", "price_id")
    ):
        raise ValueError(f"{label} requires exact TokenDance identifiers")
    return source_route


def _rates(route: dict[str, Any], *, label: str) -> dict[str, Decimal]:
    rates = route.get("rates_cny_per_million_tokens")
    if not isinstance(rates, dict) or set(rates) != {
        "uncached_input",
        "cached_input",
        "output",
    }:
        raise ValueError(f"{label} has invalid rates")
    return {
        name: _decimal_string(rates[name], label=f"{label} {name}")
        for name in rates
    }


def validate_pricing_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Validate and return one normalized public pricing snapshot."""

    require_schema(snapshot, "benchmark.model_pricing_snapshot", require_current=True)
    snapshot_id = validate_path_segment(
        str(snapshot.get("snapshot_id") or ""), "pricing snapshot id"
    )
    if snapshot.get("currency") != "CNY":
        raise ValueError("pricing snapshot currency must be CNY")
    source = snapshot.get("source")
    if not isinstance(source, dict):
        raise ValueError("pricing snapshot source must be an object")
    source_name = source.get("name")
    if source_name not in PRICE_SOURCE_URLS:
        raise ValueError("pricing snapshot source name is not supported")
    source_url = source.get("url")
    if (
        not isinstance(source_url, str)
        or not source_url.startswith(PRICE_SOURCE_URLS[source_name])
    ):
        raise ValueError(
            "pricing snapshot source URL does not match its declared source"
        )
    _iso_timestamp(source.get("captured_at"), label="source.captured_at")
    if source.get("effective_at") is not None:
        _iso_timestamp(source.get("effective_at"), label="source.effective_at")
    routes = snapshot.get("routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError("pricing snapshot routes must be a non-empty list")
    seen: set[tuple[str, str]] = set()
    normalized_routes: list[dict[str, Any]] = []
    for index, route in enumerate(routes):
        if not isinstance(route, dict):
            raise ValueError(f"pricing route {index} must be an object")
        provider = validate_path_segment(
            str(route.get("provider") or ""), f"pricing route {index} provider"
        )
        model = validate_path_segment(
            str(route.get("model") or ""), f"pricing route {index} model"
        )
        key = (provider, model)
        if key in seen:
            raise ValueError(f"duplicate pricing route: {provider}/{model}")
        seen.add(key)
        _source_route(route, label=f"pricing route {provider}/{model}")
        parsed_rates = _rates(route, label=f"pricing route {provider}/{model}")
        basis = route.get("cached_input_basis")
        if basis not in {"listed", "same_as_input"}:
            raise ValueError(
                f"pricing route {provider}/{model} has invalid cached input basis"
            )
        if (
            basis == "same_as_input"
            and parsed_rates["cached_input"] != parsed_rates["uncached_input"]
        ):
            raise ValueError(
                f"pricing route {provider}/{model} cached rate must equal input rate"
            )
        normalized_routes.append(route)
    deferred_routes = snapshot.get("deferred_routes", [])
    if not isinstance(deferred_routes, list):
        raise ValueError("pricing snapshot deferred_routes must be a list")
    for index, route in enumerate(deferred_routes):
        if not isinstance(route, dict):
            raise ValueError(f"deferred pricing route {index} must be an object")
        provider = validate_path_segment(
            str(route.get("provider") or ""),
            f"deferred pricing route {index} provider",
        )
        model = validate_path_segment(
            str(route.get("model") or ""), f"deferred pricing route {index} model"
        )
        key = (provider, model)
        if key in seen:
            raise ValueError(f"duplicate pricing route: {provider}/{model}")
        seen.add(key)
        label = f"deferred pricing route {provider}/{model}"
        _source_route(route, label=label)
        if route.get("reason") != "per_request_prompt_threshold":
            raise ValueError(f"{label} has unsupported deferral reason")
        context_limit = route.get("context_limit_tokens")
        if (
            isinstance(context_limit, bool)
            or not isinstance(context_limit, int)
            or context_limit <= 0
        ):
            raise ValueError(f"{label} requires a positive context limit")
        tiers = route.get("tiers")
        if not isinstance(tiers, list) or not tiers:
            raise ValueError(f"{label} requires explicit pricing tiers")
        expected_min = 0
        for tier_index, tier in enumerate(tiers):
            if not isinstance(tier, dict):
                raise ValueError(f"{label} tier {tier_index} must be an object")
            prompt_min = tier.get("prompt_tokens_min")
            prompt_max = tier.get("prompt_tokens_max")
            if (
                isinstance(prompt_min, bool)
                or not isinstance(prompt_min, int)
                or isinstance(prompt_max, bool)
                or not isinstance(prompt_max, int)
                or prompt_min != expected_min
                or prompt_max < prompt_min
            ):
                raise ValueError(f"{label} tiers must be contiguous and ordered")
            _rates(tier, label=f"{label} tier {tier_index}")
            expected_min = prompt_max + 1
        if expected_min != context_limit + 1:
            raise ValueError(f"{label} tiers must cover the declared context limit")
    flat_rates: dict[tuple[str, str], dict[str, Decimal]] = {}
    for route in normalized_routes:
        flat_rates[(route["provider"], route["model"])] = _rates(
            route, label=f"pricing route {route['provider']}/{route['model']}"
        )
    schedules = snapshot.get("time_tiered_schedules", [])
    if not isinstance(schedules, list):
        raise ValueError("pricing snapshot time_tiered_schedules must be a list")
    schedule_seen: set[tuple[str, str]] = set()
    for index, schedule in enumerate(schedules):
        if not isinstance(schedule, dict):
            raise ValueError(f"time-tiered schedule {index} must be an object")
        provider = validate_path_segment(
            str(schedule.get("provider") or ""),
            f"time-tiered schedule {index} provider",
        )
        model = validate_path_segment(
            str(schedule.get("model") or ""),
            f"time-tiered schedule {index} model",
        )
        label = f"time-tiered schedule {provider}/{model}"
        if (provider, model) in schedule_seen:
            raise ValueError(f"duplicate {label}")
        schedule_seen.add((provider, model))
        _source_route(schedule, label=label)
        if (provider, model) not in flat_rates:
            raise ValueError(f"{label} has no flat route to anchor its peak band")
        if schedule.get("timezone") not in TIME_TIER_TIMEZONES:
            raise ValueError(f"{label} has an unsupported timezone")
        windows = schedule.get("peak_windows")
        if not isinstance(windows, list) or not windows:
            raise ValueError(f"{label} requires explicit peak windows")
        for window in windows:
            if not isinstance(window, dict) or set(window) != {"start", "end"}:
                raise ValueError(f"{label} peak windows must be start/end pairs")
            start, end = window["start"], window["end"]
            if (
                not isinstance(start, str)
                or not isinstance(end, str)
                or PEAK_WINDOW_PATTERN.fullmatch(start) is None
                or PEAK_WINDOW_PATTERN.fullmatch(end) is None
                or start >= end
            ):
                raise ValueError(f"{label} peak window {window!r} is invalid")
        tiers = schedule.get("tiers")
        if not isinstance(tiers, list) or len(tiers) != 2:
            raise ValueError(f"{label} requires one peak and one off_peak tier")
        bands: dict[str, dict[str, Decimal]] = {}
        for tier in tiers:
            if not isinstance(tier, dict) or tier.get("band") not in TIME_TIER_BANDS:
                raise ValueError(f"{label} tier bands must be peak/off_peak")
            band = tier["band"]
            if band in bands:
                raise ValueError(f"{label} repeats the {band} band")
            rates = _rates(tier, label=f"{label} {band}")
            bands[band] = {key: str(value) for key, value in rates.items()}
        if bands["peak"] != {
            key: str(value) for key, value in flat_rates[(provider, model)].items()
        }:
            raise ValueError(
                f"{label} peak tier must equal the flat route rates "
                "(flat routes price the peak band)"
            )
    if snapshot.get("snapshot_id") != snapshot_id:
        raise ValueError("pricing snapshot id is not canonical")
    expected_content_hash = canonical_sha256(
        {key: value for key, value in snapshot.items() if key != "content_sha256"}
    )
    if snapshot.get("content_sha256") != expected_content_hash:
        raise ValueError("pricing snapshot content hash mismatch")
    return {
        **snapshot,
        "routes": normalized_routes,
        **({"deferred_routes": deferred_routes} if deferred_routes else {}),
        **({"time_tiered_schedules": schedules} if schedules else {}),
    }


def build_pricing_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = {"schema": schema_ref("benchmark.model_pricing_snapshot"), **payload}
    snapshot["content_sha256"] = canonical_sha256(snapshot)
    return validate_pricing_snapshot(snapshot)


def load_pricing_snapshot(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"pricing snapshot is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("pricing snapshot must be a JSON object")
    return validate_pricing_snapshot(payload)


def write_pricing_snapshot_once(output_dir: Path, snapshot: dict[str, Any]) -> Path:
    validated = validate_pricing_snapshot(snapshot)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{validated['snapshot_id']}.json"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(validated, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError as exc:
        raise ValueError(f"pricing snapshot already exists: {path}") from exc
    return path


def _money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))


def _token_cost(counts: dict[str, Any], rates: dict[str, Any]) -> Decimal:
    return (
        Decimal(int(counts.get("uncached_input_tokens") or 0))
        * Decimal(rates["uncached_input"])
        + Decimal(int(counts.get("cached_input_tokens") or 0))
        * Decimal(rates["cached_input"])
        + Decimal(int(counts.get("completion_tokens") or 0))
        * Decimal(rates["output"])
    ) / MILLION


def _window_second(value: str) -> int:
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 3600 + minute * 60


def _time_tier_band(schedule: dict[str, Any], started_at: Any) -> str | None:
    if not isinstance(started_at, str) or not started_at:
        return None
    try:
        instant = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if instant.tzinfo is None:
        return None
    local = instant.astimezone(ZoneInfo(schedule["timezone"]))
    if local.weekday() >= 5:
        return "off_peak"
    second = local.hour * 3600 + local.minute * 60 + local.second
    if any(
        _window_second(window["start"])
        <= second
        < _window_second(window["end"])
        for window in schedule["peak_windows"]
    ):
        return "peak"
    return "off_peak"


def _estimate_time_tiered_role(
    *,
    schedule: dict[str, Any],
    role_usage: dict[str, Any],
    requests: Any,
) -> dict[str, Any]:
    tiers = {
        tier["band"]: tier["rates_cny_per_million_tokens"]
        for tier in schedule["tiers"]
    }
    by_band = {
        band: {"api_calls": 0, "amount": Decimal("0")}
        for band in ("peak", "off_peak")
    }
    warnings: list[str] = []
    if not isinstance(requests, list):
        return {
            "known_amount": Decimal("0"),
            "telemetry_status": "unavailable",
            "warnings": [
                "time-tiered pricing requires per-request usage and started_at"
            ],
            "by_time_band": {
                band: {"api_calls": 0, "amount_cny": "0.000000"}
                for band in ("peak", "off_peak")
            },
            "rates_by_band": tiers,
        }
    missing_time = 0
    known_counts = {
        "uncached_input_tokens": 0,
        "cached_input_tokens": 0,
        "completion_tokens": 0,
    }
    for request in requests:
        if not isinstance(request, dict):
            raise ValueError("per-request pricing telemetry must contain objects")
        usage_available = request.get("usage_available") is not False
        if usage_available:
            for key in known_counts:
                known_counts[key] += int(request.get(key) or 0)
        band = _time_tier_band(schedule, request.get("started_at"))
        if band is None:
            if usage_available:
                missing_time += 1
            continue
        by_band[band]["api_calls"] += 1
        if not usage_available:
            continue
        by_band[band]["amount"] += _token_cost(request, tiers[band])
    aggregate_counts = {
        key: int(role_usage.get(key) or 0) for key in known_counts
    }
    if known_counts != aggregate_counts:
        raise ValueError(
            "per-request pricing telemetry does not match aggregate token usage"
        )
    if missing_time:
        warnings.append(f"{missing_time} request(s) omitted a usable started_at")
    base_status = str(role_usage.get("telemetry_status") or "unavailable")
    if base_status == "not_applicable":
        status = "not_applicable"
    elif base_status == "unavailable":
        status = "unavailable"
    elif missing_time or base_status == "partial":
        status = "partial"
    else:
        status = "complete"
    known_amount = sum(
        (record["amount"] for record in by_band.values()), Decimal("0")
    )
    return {
        "known_amount": known_amount,
        "telemetry_status": status,
        "warnings": warnings,
        "by_time_band": {
            band: {
                "api_calls": record["api_calls"],
                "amount_cny": _money(record["amount"]),
            }
            for band, record in by_band.items()
        },
        "rates_by_band": tiers,
    }


def _run_routes(run_config: dict[str, Any]) -> dict[str, tuple[str, str]]:
    method = run_config.get("method") or {}
    if method.get("producer") == "coding_agent_baseline":
        return {}
    roles: dict[str, tuple[str, str]] = {}
    for role, key in (("roster", "roster_model"), ("core_fields", "core_field_model")):
        route = method.get(key) or {}
        provider = str(route.get("provider") or "")
        model = str(route.get("model") or "")
        if not provider or not model:
            raise ValueError(f"run config is missing the {role} provider/model route")
        roles[role] = (provider, model)
    return roles


def validate_pricing_coverage(
    snapshot: dict[str, Any], routes: dict[str, tuple[str, str]]
) -> None:
    """Fail closed when a snapshot cannot price every named route."""

    snapshot = validate_pricing_snapshot(snapshot)
    prices = {
        (route["provider"], route["model"])
        for route in snapshot["routes"]
    }
    missing = [
        f"{provider}/{model}"
        for provider, model in routes.values()
        if (provider, model) not in prices
    ]
    if missing:
        raise ValueError(
            "pricing snapshot does not cover run routes: " + ", ".join(missing)
        )


def estimate_api_cost_for_routes(
    *,
    snapshot: dict[str, Any],
    snapshot_path: Path,
    routes: dict[str, tuple[str, str]],
    usage: dict[str, Any],
    request_usage_by_role: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Estimate CNY cost for named roles or stages using one price snapshot."""

    snapshot = validate_pricing_snapshot(snapshot)
    prices = {
        (route["provider"], route["model"]): route
        for route in snapshot["routes"]
    }
    schedules = {
        (schedule["provider"], schedule["model"]): schedule
        for schedule in snapshot.get("time_tiered_schedules", [])
    }
    if not routes:
        return {
            "status": "not_applicable",
            "currency": "CNY",
            "total_cny": "0.000000",
            "known_subtotal_cny": "0.000000",
            "by_role": {},
            "formula_version": COST_FORMULA_VERSION,
            "pricing_snapshot": {
                "snapshot_id": snapshot["snapshot_id"],
                "sha256": sha256_file(snapshot_path),
                "source_url": snapshot["source"]["url"],
                "captured_at": snapshot["source"]["captured_at"],
            },
        }
    validate_pricing_coverage(snapshot, routes)
    by_role_usage = usage.get("by_role") if isinstance(usage, dict) else None
    if not isinstance(by_role_usage, dict):
        raise ValueError("run usage must contain by_role telemetry")
    by_role: dict[str, Any] = {}
    known_total = Decimal("0")
    any_unavailable = False
    statuses: set[str] = set()
    for role, route_key in routes.items():
        role_usage = by_role_usage.get(role)
        if not isinstance(role_usage, dict):
            raise ValueError(f"run usage is missing role: {role}")
        price = prices[route_key]
        rates = price["rates_cny_per_million_tokens"]
        role_extra: dict[str, Any] = {
            "pricing_basis": "flat_route",
            "warnings": [],
        }
        schedule = schedules.get(route_key)
        if schedule is not None:
            tiered = _estimate_time_tiered_role(
                schedule=schedule,
                role_usage=role_usage,
                requests=(request_usage_by_role or {}).get(role),
            )
            known_amount = tiered["known_amount"]
            telemetry_status = tiered["telemetry_status"]
            role_extra = {
                "pricing_basis": "time_tiered_per_request",
                "timezone": schedule["timezone"],
                "by_time_band": tiered["by_time_band"],
                "rates_cny_per_million_tokens_by_band": tiered[
                    "rates_by_band"
                ],
                "warnings": tiered["warnings"],
            }
        else:
            telemetry_status = str(
                role_usage.get("telemetry_status") or "unavailable"
            )
            if telemetry_status == "unavailable":
                known_amount = Decimal("0")
            else:
                known_amount = _token_cost(role_usage, rates)
        statuses.add(telemetry_status)
        if telemetry_status == "unavailable":
            amount: str | None = None
            any_unavailable = True
        else:
            known_total += known_amount
            amount = (
                _money(known_amount)
                if telemetry_status in {"complete", "not_applicable"}
                else None
            )
        by_role[role] = {
            "provider": route_key[0],
            "model": route_key[1],
            "telemetry_status": telemetry_status,
            "amount_cny": amount,
            "known_subtotal_cny": _money(known_amount),
            "rates_cny_per_million_tokens": dict(rates),
            **role_extra,
        }
    if statuses <= {"not_applicable"}:
        status = "not_applicable"
    elif any_unavailable:
        status = "partial" if known_total else "unavailable"
    elif statuses <= {"complete", "not_applicable"}:
        status = "complete"
    else:
        status = "partial"
    amount_complete = status in {"complete", "not_applicable"}
    return {
        "status": status,
        "currency": "CNY",
        "total_cny": _money(known_total) if amount_complete else None,
        "known_subtotal_cny": _money(known_total),
        "by_role": by_role,
        "formula_version": COST_FORMULA_VERSION,
        "pricing_snapshot": {
            "snapshot_id": snapshot["snapshot_id"],
            "sha256": sha256_file(snapshot_path),
            "source_url": snapshot["source"]["url"],
            "captured_at": snapshot["source"]["captured_at"],
        },
    }


def estimate_api_cost(
    *,
    snapshot: dict[str, Any],
    snapshot_path: Path,
    run_config: dict[str, Any],
    usage: dict[str, Any],
    request_usage_by_role: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Estimate CNY cost without treating reasoning tokens as a separate charge."""

    return estimate_api_cost_for_routes(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        routes=_run_routes(run_config),
        usage=usage,
        request_usage_by_role=request_usage_by_role,
    )
