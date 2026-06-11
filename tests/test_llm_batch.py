from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from stella.lit.llm_batch import chat_completion_json, extract_json_object, shard_items

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
