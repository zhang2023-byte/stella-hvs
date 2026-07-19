from __future__ import annotations

import json
import unittest

from stella.benchmark.structured_output import (
    JSON_OBJECT,
    STRICT_JSON_SCHEMA,
    TOOL_SUBMISSION,
    StructuredOutputError,
    apply_structured_output_request,
    parse_structured_output,
    resolve_structured_output_contract,
    synthetic_long_context,
)
from stella.benchmark.run_contract import build_method_fingerprint
from stella.benchmark.roster_bundle import roster_shared_key
from stella.benchmark.roster_bundle import canonical_sha256


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "result": {"type": "string", "enum": ["ok"]},
        "count": {"type": "integer"},
    },
    "required": ["result", "count"],
}


def response(*, content: str = "", tool_calls: list[dict] | None = None) -> dict:
    message = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def tool_call(name: str, arguments: object) -> dict:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {
        "id": "call-1",
        "type": "function",
        "function": {"name": name, "arguments": raw},
    }


class StructuredOutputContractTests(unittest.TestCase):
    def test_exact_routes_resolve_tool_submission_and_freeze_overrides(self) -> None:
        deepseek = resolve_structured_output_contract(
            model="deepseek-v4-pro",
            provider={"only": ["deepseek"]},
            mode=TOOL_SUBMISSION,
        )
        glm = resolve_structured_output_contract(
            model="glm-5.2",
            provider={"only": ["bigmodel"]},
            mode=TOOL_SUBMISSION,
        )
        self.assertEqual(deepseek["request_overrides"], {"thinking": {"type": "disabled"}})
        self.assertEqual(glm["request_overrides"], {})
        self.assertEqual(deepseek["provider"], "deepseek")

    def test_unknown_route_and_unsupported_mode_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "undeclared structured-output route"):
            resolve_structured_output_contract(
                model="deepseek-v4-pro",
                provider={"only": ["other"]},
                mode=TOOL_SUBMISSION,
            )
        with self.assertRaisesRegex(ValueError, "does not support.*strict_json_schema"):
            resolve_structured_output_contract(
                model="deepseek-v4-pro",
                provider={"only": ["deepseek"]},
                mode=STRICT_JSON_SCHEMA,
            )

    def test_tool_request_is_forced_and_uses_typed_schema(self) -> None:
        contract = resolve_structured_output_contract(
            model="deepseek-v4-pro",
            provider={"only": ["deepseek"]},
            mode=TOOL_SUBMISSION,
        )
        extra = apply_structured_output_request(
            {"provider": {"only": ["deepseek"]}},
            contract=contract,
            schema=SCHEMA,
            tool_name="submit_result",
        )
        self.assertEqual(extra["tools"][0]["function"]["parameters"], SCHEMA)
        self.assertEqual(extra["tool_choice"]["function"]["name"], "submit_result")
        self.assertEqual(extra["thinking"], {"type": "disabled"})
        self.assertNotIn("response_format", extra)

    def test_tool_call_happy_path(self) -> None:
        payload = parse_structured_output(
            response(tool_calls=[tool_call("submit_result", {"result": "ok", "count": 1})]),
            mode=TOOL_SUBMISSION,
            schema=SCHEMA,
            tool_name="submit_result",
        )
        self.assertEqual(payload, {"result": "ok", "count": 1})

    def test_tool_call_rejects_missing_wrong_or_multiple(self) -> None:
        cases = (
            response(content='{"result":"ok","count":1}'),
            response(tool_calls=[tool_call("wrong", {"result": "ok", "count": 1})]),
            response(tool_calls=[tool_call("submit_result", {"result": "ok", "count": 1}), tool_call("submit_result", {"result": "ok", "count": 1})]),
        )
        for item in cases:
            with self.subTest(item=item), self.assertRaises(StructuredOutputError):
                parse_structured_output(
                    item,
                    mode=TOOL_SUBMISSION,
                    schema=SCHEMA,
                    tool_name="submit_result",
                )

    def test_tool_call_rejects_malformed_or_schema_invalid_arguments(self) -> None:
        cases = (
            tool_call("submit_result", "{broken"),
            tool_call("submit_result", {"result": "bad", "count": 1}),
            tool_call("submit_result", {"result": "ok", "count": "1"}),
            tool_call("submit_result", {"result": "ok", "count": 1, "extra": True}),
        )
        for item in cases:
            with self.subTest(item=item), self.assertRaises(StructuredOutputError):
                parse_structured_output(
                    response(tool_calls=[item]),
                    mode=TOOL_SUBMISSION,
                    schema=SCHEMA,
                    tool_name="submit_result",
                )

    def test_json_object_uses_exact_json_and_local_typed_validation(self) -> None:
        valid = parse_structured_output(
            response(content='{"result":"ok","count":1}'),
            mode=JSON_OBJECT,
            schema=SCHEMA,
            tool_name="unused",
        )
        self.assertEqual(valid["count"], 1)
        for content in ('```json\n{"result":"ok","count":1}\n```', '{"result":"ok","count":"1"}'):
            with self.subTest(content=content), self.assertRaises(StructuredOutputError):
                parse_structured_output(
                    response(content=content),
                    mode=JSON_OBJECT,
                    schema=SCHEMA,
                    tool_name="unused",
                )

    def test_synthetic_long_context_never_contains_caller_content(self) -> None:
        value = synthetic_long_context(120_000)
        self.assertGreaterEqual(len(value), 120_000)
        self.assertEqual(set(value.split()), {"SYNTHETIC-CONTEXT"})

    def test_frozen_mode_changes_method_fingerprint_and_roster_cache_key(self) -> None:
        tool = resolve_structured_output_contract(
            model="deepseek-v4-pro",
            provider={"only": ["deepseek"]},
            mode=TOOL_SUBMISSION,
        )
        json_object = resolve_structured_output_contract(
            model="deepseek-v4-pro",
            provider={"only": ["deepseek"]},
            mode=JSON_OBJECT,
        )
        base_method = {"producer": "p", "parameters": {"structured_output": tool}}
        changed_method = {"producer": "p", "parameters": {"structured_output": json_object}}
        self.assertNotEqual(
            build_method_fingerprint(base_method),
            build_method_fingerprint(changed_method),
        )
        common = dict(
            method="B",
            arxiv_id="0000.00000",
            model="deepseek-v4-pro",
            provider={"provider": {"only": ["deepseek"]}},
            prompt_sha256="p",
            rule_sha256="r",
            context_sha256="c",
            code_version="v",
            reviewer_model="glm-5.2",
            reviewer_provider={"provider": {"only": ["bigmodel"]}},
            reviewer_prompt_sha256="rp",
            reviewer_rule_sha256="rr",
        )
        first, _ = roster_shared_key(
            **{
                **common,
                "prompt_sha256": canonical_sha256(
                    {"prompt": "p", "structured_output": tool}
                ),
            }
        )
        second, _ = roster_shared_key(
            **{
                **common,
                "prompt_sha256": canonical_sha256(
                    {"prompt": "p", "structured_output": json_object}
                ),
            }
        )
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
