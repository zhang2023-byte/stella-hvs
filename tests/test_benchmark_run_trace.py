from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from stella.benchmark.context_pack import PackedContext
from stella.benchmark.run_trace import RunTrace, response_trace_metadata
from stella.benchmark.tool_loop import ContextFS, ReactUnit
from stella.lit.llm_batch import build_chat_completion_payload


class RunTraceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.trace = RunTrace(
            self.root,
            campaign_id="hvs-extraction-v2",
            run_id="dev-c-001",
            method="C",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_blobs_are_content_addressed_compressed_and_deduplicated(self) -> None:
        first = self.trace.store_blob("llm.request", {"messages": [{"role": "user", "content": "hello"}]})
        second = self.trace.store_blob("llm.request", {"messages": [{"role": "user", "content": "hello"}]})

        self.assertEqual(first, second)
        self.assertEqual(self.trace.read_blob(first["sha256"])["payload"]["messages"][0]["content"], "hello")
        self.assertEqual(len(list(self.trace.blobs_dir.glob("*.json.gz"))), 1)

    def test_event_sequences_are_thread_safe_and_resumable(self) -> None:
        def emit(number: int) -> None:
            self.trace.emit("tool.completed", data={"number": number})

        threads = [threading.Thread(target=emit, args=(number,)) for number in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        events = self.trace.read_events()
        self.assertEqual([event["seq"] for event in events], list(range(1, 13)))
        reopened = RunTrace(
            self.root,
            campaign_id="hvs-extraction-v2",
            run_id="dev-c-001",
            method="C",
        )
        self.assertEqual(reopened.emit("run.resumed")["seq"], 13)

    def test_event_references_blob_and_normalizes_usage(self) -> None:
        event = self.trace.emit(
            "llm.response.completed",
            paper_id="1804.10179",
            stage="plan",
            payload_kind="llm.response",
            payload={"model": "deepseek-v4-pro"},
            usage={
                "prompt_tokens": 12,
                "completion_tokens": 4,
                "prompt_tokens_details": {"cached_tokens": 9},
                "completion_tokens_details": {"reasoning_tokens": 2},
            },
        )

        self.assertEqual(event["usage_delta"]["prompt_cache_hit_tokens"], 9)
        self.assertEqual(event["usage_delta"]["reasoning_tokens"], 2)
        self.assertRegex(event["payload_ref"]["sha256"], r"^[0-9a-f]{64}$")
        line = json.loads(self.trace.events_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(line["schema"], {"name": "benchmark.run_event", "version": 2})

    def test_v2_event_records_graph_and_call_relationships(self) -> None:
        event = self.trace.emit(
            "llm.response.delta",
            paper_id="1804.10179",
            stage="plan",
            call_id="1804.10179:plan:1",
            node_id="plan",
            source_node_id="provider",
            target_node_id="plan",
            attempt=2,
            parent_seq=1,
        )
        self.assertEqual(event["call_id"], "1804.10179:plan:1")
        self.assertEqual(event["source_node_id"], "provider")
        self.assertEqual(event["target_node_id"], "plan")
        self.assertEqual(event["attempt"], 2)

    def test_response_metadata_marks_provider_reasoning_without_inventing_it(self) -> None:
        metadata = response_trace_metadata(
            {
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "answer",
                            "reasoning_content": "provider trace",
                            "tool_calls": [{"id": "call-1"}],
                        },
                    }
                ],
            }
        )
        self.assertTrue(metadata["provider_reasoning_available"])
        self.assertEqual(metadata["tool_call_count"], 1)
        self.assertFalse(response_trace_metadata({"choices": [{"message": {}}]})["provider_reasoning_available"])

    def test_rejects_invalid_blob_hash(self) -> None:
        with self.assertRaisesRegex(ValueError, "blob hash"):
            self.trace.read_blob("../secret")

    def test_read_only_trace_does_not_create_directories(self) -> None:
        root = self.root / "read-only"
        trace = RunTrace(
            root,
            campaign_id="campaign",
            run_id="missing-run",
            method="unknown",
            create=False,
        )
        self.assertEqual(trace.read_events(), [])
        self.assertFalse(root.exists())

    def test_incremental_reader_only_reads_appended_events(self) -> None:
        self.trace.emit("paper.started")
        self.assertEqual([item["seq"] for item in self.trace.read_events(after=0)], [1])
        self.assertEqual(self.trace.read_events(after=1), [])
        self.trace.emit("paper.completed")
        self.assertEqual([item["seq"] for item in self.trace.read_events(after=1)], [2])

    def test_shared_builder_matches_the_transport_json_body(self) -> None:
        payload = build_chat_completion_payload(
            model="model-a",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0,
            max_tokens=123,
            extra_body={"provider": {"only": ["one"]}, "model": "cannot-override"},
        )
        self.assertEqual(payload["model"], "model-a")
        self.assertEqual(payload["max_tokens"], 123)
        self.assertEqual(payload["provider"], {"only": ["one"]})
        self.assertNotIn("extra_body", payload)
        self.assertNotIn("timeout_seconds", payload)

    def test_tool_loop_trace_contains_only_exact_credential_free_request_body(self) -> None:
        def fail_transport(**_: object) -> dict:
            raise RuntimeError("stop after request trace")

        unit = ReactUnit(
            name="review",
            kind="review",
            system_prompt="system",
            task_prompt="task",
            fs=ContextFS(PackedContext(text="")),
            submit_name="submit_review",
            submit_key="review",
            submit_check=lambda _: [],
            transport=fail_transport,
            transport_kwargs={
                "api_key": "secret-key",
                "base_url": "https://secret.example/v1",
                "model": "reviewer-model",
                "temperature": 0,
                "timeout_seconds": 1800,
                "extra_body": {"provider": {"only": ["provider-a"]}},
            },
            archive=lambda *_: None,
            usage_totals={},
            trace=self.trace,
            trace_paper_id="1804.10179",
        )
        with self.assertRaisesRegex(RuntimeError, "stop after request trace"):
            unit.run(budget=1)

        event = self.trace.read_events()[0]
        payload = self.trace.read_blob(event["payload_ref"]["sha256"])["payload"]
        self.assertEqual(payload["model"], "reviewer-model")
        self.assertEqual(payload["provider"], {"only": ["provider-a"]})
        self.assertIn("tools", payload)
        self.assertEqual(payload["tool_choice"], "auto")
        for forbidden in ("api_key", "base_url", "timeout_seconds", "extra_body"):
            self.assertNotIn(forbidden, payload)


if __name__ == "__main__":
    unittest.main()
