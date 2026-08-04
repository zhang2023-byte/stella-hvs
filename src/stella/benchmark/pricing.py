"""Immutable TokenDance price snapshots and reproducible API-cost estimates."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from stella.benchmark.campaign import sha256_file
from stella.benchmark.paths import validate_path_segment
from stella.benchmark.run_contract import canonical_sha256
from stella.schema_registry import require_schema, schema_ref

PRICE_SOURCE_URL = "https://tokendance.space/models"
COST_FORMULA_VERSION = "1.0.0"
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
    if source.get("name") != "TokenDance":
        raise ValueError("pricing snapshot source name must be TokenDance")
    source_url = source.get("url")
    if not isinstance(source_url, str) or not source_url.startswith(
        PRICE_SOURCE_URL
    ):
        raise ValueError("pricing snapshot source URL must be TokenDance models")
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
) -> dict[str, Any]:
    """Estimate CNY cost for named roles or stages using one price snapshot."""

    snapshot = validate_pricing_snapshot(snapshot)
    prices = {
        (route["provider"], route["model"]): route
        for route in snapshot["routes"]
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
        telemetry_status = str(role_usage.get("telemetry_status") or "unavailable")
        statuses.add(telemetry_status)
        if telemetry_status == "unavailable":
            known_amount = Decimal("0")
            amount: str | None = None
            any_unavailable = True
        else:
            known_amount = (
                Decimal(int(role_usage.get("uncached_input_tokens") or 0))
                * Decimal(rates["uncached_input"])
                + Decimal(int(role_usage.get("cached_input_tokens") or 0))
                * Decimal(rates["cached_input"])
                + Decimal(int(role_usage.get("completion_tokens") or 0))
                * Decimal(rates["output"])
            ) / MILLION
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
) -> dict[str, Any]:
    """Estimate CNY cost without treating reasoning tokens as a separate charge."""

    return estimate_api_cost_for_routes(
        snapshot=snapshot,
        snapshot_path=snapshot_path,
        routes=_run_routes(run_config),
        usage=usage,
    )
