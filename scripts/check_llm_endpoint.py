#!/usr/bin/env python3
"""Smoke-test the configured LLM gateway (Token Dance by default).

Two checks:

1. Model listing (no auth): GET <base>/models and confirm the configured
   LLM_MODEL id exists on the gateway.
2. Chat round-trip (needs LLM_API_KEY): one tiny chat completion at
   temperature 0. Prints the model id the gateway *actually served* (this
   is the constructive value the benchmark pipeline records as
   tooling.model_id), token usage, and warns if the reply to an
   English-only instruction contains CJK characters — an early signal of
   the "model drifts into Chinese" failure mode.

Run after filling LLM_API_KEY in .env:
    conda run -n stella-env python scripts/check_llm_endpoint.py
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

from stella.benchmark.structured_output import (
    STRUCTURED_OUTPUT_MODES,
    TOOL_SUBMISSION,
    apply_structured_output_request,
    parse_structured_output,
    resolve_structured_output_contract,
    synthetic_long_context,
)
from stella.hvs_extraction.method_config import (
    ROSTER_REASONING_EFFORTS,
    ROSTER_THINKING_TYPES,
    default_hvs_extraction_method_config,
)
from stella.hvs_extraction.submission_schema import (
    build_roster_submission_schema,
)
from stella.lit.env import env_value, load_env_files
from stella.lit.llm_batch import chat_completion_raw

WORKSPACE = Path(__file__).resolve().parents[1]
CJK_RE = re.compile(r"[一-鿿]")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify LLM gateway connectivity, model availability, and key."
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id to test. Default: LLM_MODEL from the environment.",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="Only check the model listing; do not spend tokens.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds. Default: 120.",
    )
    parser.add_argument(
        "--structured-probe",
        action="store_true",
        help="Run a synthetic forced-tool capability probe and print metadata only.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Exact provider slug for --structured-probe.",
    )
    parser.add_argument(
        "--long-context-chars",
        type=int,
        default=0,
        help="Synthetic context size for --structured-probe; never reads paper content.",
    )
    parser.add_argument(
        "--mode",
        choices=sorted(STRUCTURED_OUTPUT_MODES),
        default=TOOL_SUBMISSION,
        help="Structured-output mode for --structured-probe.",
    )
    parser.add_argument(
        "--thinking",
        choices=sorted(ROSTER_THINKING_TYPES),
        default=None,
        help="Thinking override merged after the probe contract (roster-stage order).",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=sorted(ROSTER_REASONING_EFFORTS),
        default=None,
        help="Reasoning effort for --structured-probe; requires --thinking enabled.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Stream the probe request; long thinking generations need flowing bytes.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=600,
        help="max_tokens for --structured-probe. Default: 600.",
    )
    return parser


def fetch_models(base_url: str, timeout: float) -> dict[str, dict]:
    request = urllib.request.Request(f"{base_url.rstrip('/')}/models")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {entry["id"]: entry for entry in payload.get("data", [])}


def chat_once(base_url: str, api_key: str, model: str, timeout: float) -> dict:
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "max_tokens": 40,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Reply in English only with exactly: "
                        "ENDPOINT OK. Then name this model."
                    ),
                }
            ],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def structured_probe_once(
    *,
    base_url: str,
    api_key: str,
    model: str,
    provider: str,
    timeout: float,
    long_context_chars: int,
    mode: str = TOOL_SUBMISSION,
    thinking: str | None = None,
    reasoning_effort: str | None = None,
    stream: bool = False,
    max_tokens: int = 600,
) -> dict:
    """Probe one exact route without returning prompt or response content."""

    if reasoning_effort is not None and thinking != "enabled":
        raise ValueError("probe reasoning effort requires --thinking enabled")
    contract = resolve_structured_output_contract(
        model=model,
        provider={"only": [provider]},
        mode=mode,
    )
    schema = build_roster_submission_schema(["synthetic.tex"])
    extra = apply_structured_output_request(
        {"provider": {"only": [provider]}},
        contract=contract,
        schema=schema,
        tool_name="submit_synthetic_roster",
    )
    if thinking is not None:
        if "thinking" in extra:
            raise ValueError("probe thinking conflicts with the declared contract")
        extra["thinking"] = {"type": thinking}
    if reasoning_effort is not None:
        extra["reasoning_effort"] = reasoning_effort
    context = synthetic_long_context(long_context_chars) if long_context_chars else ""
    instruction = " Submit an empty synthetic roster with status no_candidates."
    if mode != TOOL_SUBMISSION:
        instruction += (
            " Respond with exactly one JSON object satisfying this schema:\n"
            + json.dumps(schema, ensure_ascii=False)
        )
    messages = [
        {"role": "system", "content": "Synthetic JSON capability probe."},
        {
            "role": "user",
            "content": context + instruction,
        },
    ]
    reply = chat_completion_raw(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=max_tokens,
        timeout_seconds=int(timeout),
        attempts=1,
        extra_body=extra,
        stream=stream,
    )
    parse_structured_output(
        reply,
        mode=mode,
        schema=schema,
        tool_name="submit_synthetic_roster",
    )
    message = ((reply.get("choices") or [{}])[0].get("message") or {})
    return {
        "ok": True,
        "requested_model": model,
        "provider": provider,
        "served_model": str(reply.get("model") or ""),
        "mode": mode,
        "thinking": thinking,
        "reasoning_effort": reasoning_effort,
        "stream": stream,
        "max_tokens": max_tokens,
        "long_context_chars": max(0, long_context_chars),
        "tool_calls": len(message.get("tool_calls") or []),
        "content_present": bool(message.get("content")),
        "usage": dict(reply.get("usage") or {}),
    }


def main() -> int:
    args = build_parser().parse_args()
    load_env_files(WORKSPACE)
    base_url = env_value("LLM_BASE_URL")
    if not base_url:
        raise SystemExit("LLM_BASE_URL is not set; fill .env first")
    model = args.model or env_value("LLM_MODEL")
    if not model:
        raise SystemExit("LLM_MODEL is not set; fill .env first")

    print(f"Gateway: {base_url}")
    models = fetch_models(base_url, args.timeout)
    print(f"Listed models: {len(models)}")
    method = default_hvs_extraction_method_config(WORKSPACE)
    configured_routes = (
        str(method.roster_model.model),
        str(method.core_field_model.model),
    )
    for candidate in dict.fromkeys((model, *configured_routes)):
        entry = models.get(candidate)
        marker = "requested  ->" if candidate == model else "workflow   ->"
        if entry is None:
            print(f"{marker} {candidate}: NOT LISTED")
        else:
            print(
                f"{marker} {candidate}: ok "
                f"(context {entry.get('context_length', '?')})"
            )
    if model not in models:
        print("FAIL: configured model is not available on the gateway")
        return 1

    if args.skip_chat and not args.structured_probe:
        print("Chat round-trip skipped (--skip-chat).")
        return 0
    api_key = env_value("LLM_API_KEY")
    if not api_key:
        print("LLM_API_KEY is empty: listing check passed, chat check skipped.")
        print("Fill the key in .env and rerun for the full test.")
        return 0

    if args.structured_probe:
        if not args.provider:
            raise SystemExit("--structured-probe requires --provider")
        result = structured_probe_once(
            base_url=base_url,
            api_key=api_key,
            model=model,
            provider=args.provider,
            timeout=args.timeout,
            long_context_chars=max(0, args.long_context_chars),
            mode=args.mode,
            thinking=args.thinking,
            reasoning_effort=args.reasoning_effort,
            stream=args.stream,
            max_tokens=args.max_tokens,
        )
        print("Structured probe: " + json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    reply = chat_once(base_url, api_key, model, args.timeout)
    served_model = reply.get("model", "")
    usage = reply.get("usage", {})
    content = (reply.get("choices") or [{}])[0].get("message", {}).get("content", "")
    print(f"Served model id: {served_model or '?'} (requested {model})")
    print(
        "Usage: "
        f"prompt={usage.get('prompt_tokens', '?')} "
        f"completion={usage.get('completion_tokens', '?')} "
        f"total={usage.get('total_tokens', '?')}"
    )
    print(f"Reply: {content.strip()[:120]}")
    if CJK_RE.search(content):
        print(
            "WARNING: reply to an English-only instruction contains CJK "
            "characters; the extraction pipeline's language guard matters "
            "for this model."
        )
    print("Chat round-trip OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
