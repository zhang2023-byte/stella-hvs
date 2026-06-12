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

from stella.lit.env import env_value, load_env_files

WORKSPACE = Path(__file__).resolve().parents[1]
CJK_RE = re.compile(r"[一-鿿]")
SUPPLEMENT_MODELS = ("kimi-k2.6", "minimax-m3", "mimo-v2.5-pro")


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
    for candidate in (model, *SUPPLEMENT_MODELS):
        entry = models.get(candidate)
        marker = "configured ->" if candidate == model else "supplement  ->"
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

    if args.skip_chat:
        print("Chat round-trip skipped (--skip-chat).")
        return 0
    api_key = env_value("LLM_API_KEY")
    if not api_key:
        print("LLM_API_KEY is empty: listing check passed, chat check skipped.")
        print("Fill the key in .env and rerun for the full test.")
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
