from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from stella.lit.llm_batch import (
    LLMTransportError,
    chat_completion_json,
    chat_completion_raw,
    extract_json_object,
    shard_items,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_catalog_review_batch.py"
SPEC = importlib.util.spec_from_file_location("run_catalog_review_batch", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
batch_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch_cli)


class ExtractJsonObjectTest(unittest.TestCase):
    def test_plain_json_object(self) -> None:
        self.assertEqual(extract_json_object('{"a": 1}'), {"a": 1})

    def test_fenced_json_object(self) -> None:
        self.assertEqual(extract_json_object('```json\n{"a": 1}\n```'), {"a": 1})

    def test_embedded_json_object(self) -> None:
        self.assertEqual(extract_json_object('Sure, here you go: {"a": 1} done'), {"a": 1})

    def test_non_object_rejected(self) -> None:
        with self.assertRaises(ValueError):
            extract_json_object("[1, 2, 3]")


class ShardItemsTest(unittest.TestCase):
    def test_shards_partition_items(self) -> None:
        items = list(range(10))
        shards = [shard_items(items, shard_index=i, shard_count=3) for i in range(3)]
        self.assertEqual(sorted(item for shard in shards for item in shard), items)
        self.assertEqual(shards[0], [0, 3, 6, 9])

    def test_invalid_shard_arguments(self) -> None:
        with self.assertRaises(ValueError):
            shard_items([1], shard_index=0, shard_count=0)
        with self.assertRaises(ValueError):
            shard_items([1], shard_index=2, shard_count=2)


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def sse_response(*chunks: dict | str) -> FakeResponse:
    lines = [f"data: {json.dumps(chunk)}\n\n" if isinstance(chunk, dict) else f"data: {chunk}\n\n" for chunk in chunks]
    return FakeResponse("".join(lines).encode("utf-8"))


class BrokenStream:
    def __enter__(self) -> "BrokenStream":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def __iter__(self):
        yield b'data: {"id":"x","choices":[{"index":0,"delta":{"content":"partial"}}]}\n\n'
        raise OSError("connection dropped")


class ChatCompletionRawStreamingTest(unittest.TestCase):
    def test_local_openai_compatible_streaming_server_integration(self) -> None:
        received: list[dict] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                received.append(json.loads(self.rfile.read(length)))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in (
                    {"id": "local-stream", "model": "fake-served", "choices": [{"index": 0, "delta": {"content": "local "}}]},
                    {"choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}]},
                    {"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 2}},
                ):
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            def log_message(self, *_: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = chat_completion_raw(
                api_key="fake-key",
                base_url=f"http://127.0.0.1:{server.server_address[1]}/v1",
                model="requested",
                messages=[{"role": "user", "content": "hello"}],
                stream=True,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result["choices"][0]["message"]["content"], "local ok")
        self.assertEqual(result["usage"]["completion_tokens"], 2)
        self.assertTrue(received[0]["stream"])

    def test_reconstructs_content_reasoning_tool_calls_and_usage(self) -> None:
        response = sse_response(
            {"id": "chat-1", "model": "served-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "hel", "reasoning_content": "visible "}}]},
            {"choices": [{"index": 0, "delta": {"content": "lo", "reasoning_content": "reason", "tool_calls": [{"index": 0, "id": "call-1", "type": "function", "function": {"name": "read_", "arguments": '{"p"'}}]}}]},
            {"choices": [{"index": 0, "delta": {"tool_calls": [{"index": 0, "function": {"name": "lines", "arguments": ":1}"}}]}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "completion_tokens_details": {"reasoning_tokens": 3}}},
            "[DONE]",
        )
        events: list[dict] = []
        with patch("stella.lit.llm_batch.urllib.request.urlopen", return_value=response) as urlopen:
            result = chat_completion_raw(
                api_key="key", base_url="https://example.test/v1", model="requested-model",
                messages=[{"role": "user", "content": "hi"}], stream=True,
                on_stream_event=events.append,
            )
        message = result["choices"][0]["message"]
        self.assertEqual(message["content"], "hello")
        self.assertEqual(message["reasoning_content"], "visible reason")
        self.assertEqual(message["tool_calls"][0]["function"], {"name": "read_lines", "arguments": '{"p":1}'})
        self.assertEqual(result["usage"]["completion_tokens_details"]["reasoning_tokens"], 3)
        self.assertEqual(result["model"], "served-model")
        channels = [event.get("channel") for event in events if event["type"] == "response.delta"]
        self.assertEqual(channels.count("content"), 2)
        self.assertIn("reasoning", channels)
        self.assertIn("tool_call", channels)
        sent = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertTrue(sent["stream"])
        self.assertTrue(sent["stream_options"]["include_usage"])

    def test_retries_midstream_disconnect_and_emits_retry_events(self) -> None:
        completed = sse_response(
            {"id": "chat-2", "model": "model", "choices": [{"index": 0, "delta": {"content": "complete"}, "finish_reason": "stop"}]},
            "[DONE]",
        )
        events: list[dict] = []
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=[BrokenStream(), completed]), patch("stella.lit.llm_batch.time.sleep"):
            result = chat_completion_raw(
                api_key="key", base_url="https://example.test/v1", model="model",
                messages=[], stream=True, attempts=2, on_stream_event=events.append,
            )
        self.assertEqual(result["choices"][0]["message"]["content"], "complete")
        retry = next(event for event in events if event["type"] == "retry.scheduled")
        self.assertEqual(retry["next_attempt"], 2)
        self.assertTrue(any(event["type"] == "stream.interrupted" for event in events))
        self.assertTrue(any(event["type"] == "response.delta" and event.get("text") == "partial" for event in events))

    def test_retries_when_stream_reaches_eof_without_terminal_marker(self) -> None:
        truncated = sse_response(
            {"id": "chat-short", "choices": [{"index": 0, "delta": {"content": "partial"}}]},
        )
        completed = sse_response(
            {"id": "chat-ok", "choices": [{"index": 0, "delta": {"content": "complete"}, "finish_reason": "stop"}]},
            "[DONE]",
        )
        events: list[dict] = []
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=[truncated, completed]), patch("stella.lit.llm_batch.time.sleep"):
            result = chat_completion_raw(
                api_key="key", base_url="https://example.test/v1", model="model",
                messages=[], stream=True, attempts=2, on_stream_event=events.append,
            )
        self.assertEqual(result["choices"][0]["message"]["content"], "complete")
        self.assertTrue(any(event["type"] == "stream.interrupted" for event in events))
        self.assertTrue(any(event["type"] == "retry.scheduled" for event in events))

    def test_falls_back_only_when_provider_rejects_streaming_before_response(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions", 400, "bad request", {},
            io.BytesIO(b'{"error":"stream is not supported"}'),
        )
        whole = FakeResponse(json.dumps({"model": "model", "choices": [{"message": {"content": "ok"}}]}).encode())
        events: list[dict] = []
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=[error, whole]) as urlopen:
            result = chat_completion_raw(
                api_key="key", base_url="https://example.test/v1", model="model",
                messages=[], stream=True, on_stream_event=events.append,
            )
        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(urlopen.call_count, 2)
        first = json.loads(urlopen.call_args_list[0].args[0].data.decode())
        second = json.loads(urlopen.call_args_list[1].args[0].data.decode())
        self.assertTrue(first["stream"])
        self.assertNotIn("stream", second)
        self.assertEqual([event["type"] for event in events], ["stream.unsupported"])

    def test_does_not_fallback_for_an_unrelated_bad_request_that_mentions_stream(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions", 400, "bad request", {},
            io.BytesIO(b'{"error":"invalid stream option value"}'),
        )
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=error) as urlopen:
            with self.assertRaises(LLMTransportError) as raised:
                chat_completion_raw(
                    api_key="key", base_url="https://example.test/v1", model="model",
                    messages=[], stream=True,
                )
        self.assertEqual(raised.exception.category, "invalid_request")
        self.assertFalse(raised.exception.manual_retry_eligible)
        self.assertEqual(urlopen.call_count, 1)

    def test_retry_exhaustion_emits_terminal_event(self) -> None:
        events: list[dict] = []
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=OSError("offline")), patch("stella.lit.llm_batch.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "2 attempts"):
                chat_completion_raw(
                    api_key="key", base_url="https://example.test/v1", model="model",
                    messages=[], stream=True, attempts=2, on_stream_event=events.append,
                )
        self.assertEqual(events[-1]["type"], "retry.exhausted")

    def test_structures_http_categories_request_id_and_retry_policy(self) -> None:
        cases = (
            (400, b'{"error":"bad request"}', "invalid_request", False, False),
            (400, b'{"error":"maximum context length exceeded"}', "context_limit", False, False),
            (401, b'unauthorized', "authentication", False, True),
            (408, b'request timeout', "timeout", True, True),
            (429, b'rate limited', "rate_limit", True, True),
            (503, b'unavailable', "server", True, True),
        )
        for status, body, category, automatic, manual in cases:
            with self.subTest(status=status, category=category):
                error = urllib.error.HTTPError(
                    "https://example.test/v1/chat/completions",
                    status,
                    "provider error",
                    {"x-request-id": "req-123"},
                    io.BytesIO(body),
                )
                with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=error), patch(
                    "stella.lit.llm_batch.time.sleep"
                ):
                    with self.assertRaises(LLMTransportError) as raised:
                        chat_completion_raw(
                            api_key="key",
                            base_url="https://example.test/v1",
                            model="model",
                            messages=[],
                            attempts=1,
                        )
                exc = raised.exception
                self.assertEqual(exc.category, category)
                self.assertEqual(exc.http_status, status)
                self.assertEqual(exc.automatic_retryable, automatic)
                self.assertEqual(exc.manual_retry_eligible, manual)
                self.assertEqual(exc.provider_request_id, "req-123")

    def test_timeout_is_structured_after_retry_exhaustion(self) -> None:
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=TimeoutError("slow")), patch(
            "stella.lit.llm_batch.time.sleep"
        ):
            with self.assertRaises(LLMTransportError) as raised:
                chat_completion_raw(
                    api_key="key",
                    base_url="https://example.test/v1",
                    model="model",
                    messages=[],
                    attempts=2,
                )
        self.assertEqual(raised.exception.category, "timeout")
        self.assertEqual(raised.exception.attempts, 2)
        self.assertTrue(raised.exception.manual_retry_eligible)

    def test_provider_parse_400_retries_once_then_succeeds(self) -> None:
        parse_error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            400,
            "bad request",
            {},
            io.BytesIO(b"Error when parsing request"),
        )
        valid = FakeResponse(
            b'{"choices":[{"message":{"content":"ok"}}]}'
        )
        with patch(
            "stella.lit.llm_batch.urllib.request.urlopen",
            side_effect=[parse_error, valid],
        ) as urlopen, patch("stella.lit.llm_batch.time.sleep"):
            response = chat_completion_raw(
                api_key="key",
                base_url="https://example.test/v1",
                model="model",
                messages=[],
                attempts=5,
            )
        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        self.assertEqual(urlopen.call_count, 2)

    def test_provider_parse_400_is_bounded_to_two_attempts(self) -> None:
        def parse_error() -> urllib.error.HTTPError:
            return urllib.error.HTTPError(
                "https://example.test/v1/chat/completions",
                400,
                "bad request",
                {},
                io.BytesIO(b"Error when parsing request"),
            )

        with patch(
            "stella.lit.llm_batch.urllib.request.urlopen",
            side_effect=[parse_error(), parse_error(), FakeResponse(b"{}")],
        ) as urlopen, patch("stella.lit.llm_batch.time.sleep"):
            with self.assertRaises(LLMTransportError) as raised:
                chat_completion_raw(
                    api_key="key",
                    base_url="https://example.test/v1",
                    model="model",
                    messages=[],
                    attempts=5,
                )
        self.assertEqual(raised.exception.category, "provider_parse_error")
        self.assertEqual(raised.exception.attempts, 2)
        self.assertTrue(raised.exception.automatic_retryable)
        self.assertTrue(raised.exception.manual_retry_eligible)
        self.assertEqual(urlopen.call_count, 2)

    def test_malformed_whole_response_is_protocol_error_without_retry(self) -> None:
        invalid = FakeResponse(b"not-json")
        valid = FakeResponse(b'{"choices":[{"message":{"content":"unused"}}]}')
        with patch(
            "stella.lit.llm_batch.urllib.request.urlopen",
            side_effect=[invalid, valid],
        ) as urlopen:
            with self.assertRaises(LLMTransportError) as raised:
                chat_completion_raw(
                    api_key="key",
                    base_url="https://example.test/v1",
                    model="model",
                    messages=[],
                    attempts=2,
                )
        self.assertEqual(raised.exception.category, "protocol")
        self.assertFalse(raised.exception.automatic_retryable)
        self.assertFalse(raised.exception.manual_retry_eligible)
        self.assertEqual(urlopen.call_count, 1)

    def test_error_body_is_redacted_and_limited_to_32_kib(self) -> None:
        body = (
            b'{"authorization":"Bearer secret-token","api_key":"abc","message":"'
            + b"x" * (40 * 1024)
            + b'"}'
        )
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            400,
            "bad request",
            {},
            io.BytesIO(body),
        )
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(LLMTransportError) as raised:
                chat_completion_raw(
                    api_key="key",
                    base_url="https://example.test/v1",
                    model="model",
                    messages=[],
                    attempts=1,
                )
        excerpt = raised.exception.response_body_excerpt
        self.assertNotIn("secret-token", excerpt)
        self.assertNotIn('"abc"', excerpt)
        self.assertLessEqual(len(excerpt.encode("utf-8")), 32 * 1024)

    def test_plain_text_secret_assignments_are_redacted(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            400,
            "bad request",
            {},
            io.BytesIO(b"api_key=plain-secret authorization:Basic-secret"),
        )
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(LLMTransportError) as raised:
                chat_completion_raw(
                    api_key="key",
                    base_url="https://example.test/v1",
                    model="model",
                    messages=[],
                )
        excerpt = raised.exception.response_body_excerpt
        self.assertNotIn("plain-secret", excerpt)
        self.assertNotIn("Basic-secret", excerpt)


class ChatCompletionJsonTest(unittest.TestCase):
    def test_parses_message_content(self) -> None:
        body = json.dumps({"choices": [{"message": {"content": '{"status": "reviewed"}'}}]}).encode("utf-8")
        with patch("stella.lit.llm_batch.urllib.request.urlopen", return_value=FakeResponse(body)) as urlopen:
            result = chat_completion_json(
                api_key="key",
                base_url="https://example.test/v1",
                model="test-model",
                messages=[{"role": "user", "content": "hi"}],
            )
        self.assertEqual(result, {"status": "reviewed"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://example.test/v1/chat/completions")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["temperature"], 0)

    def test_retries_transient_failures_then_succeeds(self) -> None:
        body = json.dumps({"choices": [{"message": {"content": '{"ok": true}'}}]}).encode("utf-8")
        side_effects = [TimeoutError("slow"), FakeResponse(body)]
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=side_effects), patch(
            "stella.lit.llm_batch.time.sleep"
        ) as sleep:
            result = chat_completion_json(
                api_key="key",
                base_url="https://example.test/v1",
                model="test-model",
                messages=[{"role": "user", "content": "hi"}],
            )
        self.assertEqual(result, {"ok": True})
        sleep.assert_called_once()

    def test_exhausted_retries_raise_runtime_error(self) -> None:
        with patch("stella.lit.llm_batch.urllib.request.urlopen", side_effect=TimeoutError("slow")), patch(
            "stella.lit.llm_batch.time.sleep"
        ):
            with self.assertRaises(RuntimeError):
                chat_completion_json(
                    api_key="key",
                    base_url="https://example.test/v1",
                    model="test-model",
                    messages=[{"role": "user", "content": "hi"}],
                    attempts=2,
                )


class SelectedIdsTest(unittest.TestCase):
    def test_filters_by_month_window_and_catalog_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp)
            month_dir = notes / "2024" / "2024-05"
            month_dir.mkdir(parents=True)
            (month_dir / "2024-05.json").write_text(
                json.dumps(
                    {
                        "month": "2024-05",
                        "papers": [
                            {"arxiv_id": "2405.00001", "catalog_assessment": {"has_observational_catalog": True}},
                            {"arxiv_id": "2405.00002", "catalog_assessment": {"has_observational_catalog": False}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            out_dir = notes / "2020" / "2020-01"
            out_dir.mkdir(parents=True)
            (out_dir / "2020-01.json").write_text(
                json.dumps(
                    {
                        "month": "2020-01",
                        "papers": [
                            {"arxiv_id": "2001.00001", "catalog_assessment": {"has_observational_catalog": True}},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            ids = batch_cli.selected_ids(notes, month_from="2023-01", month_to="2026-05")

        self.assertEqual(ids, ["2405.00001"])


class BuildReviewRecordTest(unittest.TestCase):
    def test_selected_and_rejected_tables_are_recorded(self) -> None:
        inventory = {
            "paper": {"arxiv_id": "2405.00001", "title": "T", "month": "2024-05", "source_note_json": "", "links": {}},
            "source": {"source_available": True},
        }
        maps = {
            "tables": {
                "t1": {"path": "arxiv_source/main.tex", "start_line": 10, "end_line": 20, "caption": "Cat", "label": "tab:1", "latex_excerpt": "x"},
                "t2": {"path": "arxiv_source/main.tex", "start_line": 30, "end_line": 40, "caption": "Model", "label": "tab:2", "latex_excerpt": "y"},
            },
            "files": {},
            "external": {},
        }
        llm_output = {
            "status": "reviewed",
            "summary": "ok",
            "tables": [
                {"id": "t1", "catalog_role": "new_catalog", "object_scope": "multiple_objects", "data_products": ["source_ids"], "meaning": "m", "evidence": "e", "confidence": 0.9, "comments": ""}
            ],
            "resources": [],
            "rejections": [{"id": "t2", "reason": "model table"}],
        }

        record = batch_cli.build_review_record(inventory, llm_output, maps)

        self.assertEqual(record["review"]["status"], "reviewed")
        self.assertEqual(len(record["catalog_candidates"]), 1)
        self.assertEqual(record["catalog_candidates"][0]["catalog_role"], "new_catalog")
        self.assertEqual(len(record["rejected_candidates"]), 1)
        self.assertEqual(record["rejected_candidates"][0]["reason"], "model table")

    def test_missing_source_forces_source_missing_status(self) -> None:
        inventory = {"paper": {"arxiv_id": "x"}, "source": {"source_available": False}}
        record = batch_cli.build_review_record(
            inventory,
            {"status": "reviewed", "summary": "", "tables": [], "resources": [], "rejections": []},
            {"tables": {}, "files": {}, "external": {}},
        )
        self.assertEqual(record["review"]["status"], "source_missing")


if __name__ == "__main__":
    unittest.main()
