from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from stella.benchmark.context_pack import (
    PackedContext,
    numbered_lines,
    pack_paper_context,
)
from stella.benchmark.extraction_run import (
    enforce_pipeline_fields,
    find_cjk_strings,
    repair_feedback,
    run_paper,
)
from stella.lit.llm_batch import chat_completion_raw


def make_skill_files(workspace: Path) -> None:
    skill_dir = workspace / "skills" / "hvs-candidates-extraction"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Skill\nExtract.", encoding="utf-8")
    (skill_dir / "references" / "schema.md").write_text("# Schema", encoding="utf-8")
    (skill_dir / "references" / "coordinate_frames.md").write_text(
        "# Frames", encoding="utf-8"
    )


def make_paper_dir(workspace: Path, arxiv_id: str = "9901.00001") -> Path:
    paper_dir = workspace / "literature" / arxiv_id
    (paper_dir / "arxiv_source").mkdir(parents=True)
    (paper_dir / "catalog_tables").mkdir()
    (paper_dir / "audit.json").write_text(
        json.dumps(
            {
                "arxiv_id": arxiv_id,
                "title": "A synthetic paper",
                "month": "2099-01",
                "source_note_json": "",
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "catalog_review.json").write_text(
        json.dumps({"schema_version": "x", "tables": []}), encoding="utf-8"
    )
    ecsv_rel = f"literature/{arxiv_id}/catalog_tables/table-a.ecsv"
    (paper_dir / "catalog_extraction.json").write_text(
        json.dumps(
            {
                "schema_version": "x",
                "tables": [{"status": "success", "ecsv_path": ecsv_rel}],
            }
        ),
        encoding="utf-8",
    )
    (paper_dir / "catalog_tables" / "table-a.ecsv").write_text(
        "# %ECSV 1.0\nname,rv\nStarA,612.3\n", encoding="utf-8"
    )
    (paper_dir / "arxiv_source" / "paper.tex").write_text(
        "\\title{Synthetic}\nStarA has rv 612.3 km/s.\n", encoding="utf-8"
    )
    return paper_dir


class ContextPackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        make_paper_dir(self.workspace)
        self.ecsv = ["literature/9901.00001/catalog_tables/table-a.ecsv"]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def pack(self) -> PackedContext:
        return pack_paper_context(self.workspace, "9901.00001", self.ecsv)

    def test_pack_is_deterministic(self) -> None:
        self.assertEqual(self.pack().sha256, self.pack().sha256)

    def test_pack_contains_numbered_tex_and_ecsv(self) -> None:
        text = self.pack().text
        self.assertIn("1|\\title{Synthetic}", text)
        self.assertIn("3|StarA,612.3", text)
        self.assertIn("BEGIN literature/9901.00001/catalog_review.json", text)

    def test_file_order_and_kinds(self) -> None:
        kinds = [item.kind for item in self.pack().files]
        self.assertEqual(
            kinds,
            ["catalog_review", "catalog_extraction", "ecsv_table", "paper_text"],
        )

    def test_missing_declared_ecsv_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            pack_paper_context(
                self.workspace, "9901.00001", ["literature/9901.00001/nope.ecsv"]
            )

    def test_oversize_pack_refuses_truncation(self) -> None:
        with self.assertRaises(ValueError):
            pack_paper_context(
                self.workspace, "9901.00001", self.ecsv, max_chars=10
            )

    def test_numbered_lines_are_physical(self) -> None:
        self.assertEqual(numbered_lines("a\nb\n"), "1|a\n2|b")


class CjkScanTest(unittest.TestCase):
    def test_finds_cjk_paths_and_skips_raw_value(self) -> None:
        document = {
            "extraction": {"summary": "这是中文摘要"},
            "candidates": [
                {
                    "core": {
                        "raw_value": "测试",  # exempt key
                        "description": "fine english",
                    }
                }
            ],
        }
        findings = find_cjk_strings(document)
        self.assertEqual(findings, ["$.extraction.summary"])


class EnforceFieldsTest(unittest.TestCase):
    def test_model_cannot_control_provenance(self) -> None:
        skeleton = {
            "schema_version": "stella.literature_hvs_candidates.v0.1",
            "generated_at": "2099-01-01T00:00:00",
            "paper": {"arxiv_id": "9901.00001"},
            "inputs": {"ecsv_paths": []},
        }
        forged = {
            "schema_version": "evil",
            "generated_at": "1990",
            "paper": {"arxiv_id": "fake"},
            "inputs": {"ecsv_paths": ["fake"]},
            "extraction": {
                "status": "no_candidates",
                "tooling": {"model_id": "model-claims-to-be-gpt9"},
            },
        }
        document = enforce_pipeline_fields(
            forged,
            skeleton,
            served_model_id="deepseek-v4-pro",
            requested_model="deepseek-v4-pro",
            prompt_version="abc1234",
            request_parameters={"temperature": 0},
            extracted_at="2099-01-02T00:00:00",
        )
        self.assertEqual(document["schema_version"], skeleton["schema_version"])
        self.assertEqual(document["paper"], skeleton["paper"])
        self.assertEqual(document["inputs"], skeleton["inputs"])
        tooling = document["extraction"]["tooling"]
        self.assertEqual(tooling["model_id"], "deepseek-v4-pro")
        self.assertEqual(tooling["prompt_version"], "abc1234")

    def test_feedback_truncates_long_error_lists(self) -> None:
        text = repair_feedback([f"e{i}" for i in range(200)], [])
        self.assertIn("200 total, showing 80", text)


class FakeValidatorModule:
    """Stub of the frozen validator with a scripted error sequence."""

    def __init__(self, error_batches: list[list[str]]) -> None:
        self.error_batches = error_batches
        self.calls = 0

    def validate_hvs_candidates_report(self, payload, *, workspace, require_complete):
        errors = (
            self.error_batches[self.calls]
            if self.calls < len(self.error_batches)
            else []
        )
        self.calls += 1
        return type("Report", (), {"errors": errors, "warnings": ["w"]})()


def fake_response(document: dict, model: str = "deepseek-v4-pro") -> dict:
    return {
        "model": model,
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "completion_tokens_details": {"reasoning_tokens": 20},
        },
        "choices": [{"message": {"content": json.dumps(document)}}],
    }


class RunPaperTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        make_paper_dir(self.workspace)
        make_skill_files(self.workspace)
        self.run_dir = self.workspace / "run"
        self.document = {"extraction": {"status": "no_candidates", "summary": "ok"}}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_one(self, validator, transport, max_repair_rounds: int = 2) -> object:
        return run_paper(
            workspace=self.workspace,
            arxiv_id="9901.00001",
            run_dir=self.run_dir,
            api_key="k",
            base_url="https://example.invalid/v1",
            model="deepseek-v4-pro",
            prompt_version="abc1234",
            max_repair_rounds=max_repair_rounds,
            validator_module=validator,
            transport=transport,
        )

    def test_clean_first_attempt(self) -> None:
        transport = mock.Mock(return_value=fake_response(self.document))
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.usage_totals["total_tokens"], 150)
        self.assertEqual(result.usage_totals["reasoning_tokens"], 20)
        paper_dir = self.run_dir / "9901.00001"
        final = json.loads(
            (paper_dir / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(
            final["extraction"]["tooling"]["model_id"], "deepseek-v4-pro"
        )
        self.assertTrue((paper_dir / "context_manifest.json").is_file())
        self.assertTrue((paper_dir / "attempts" / "attempt-01.response.json").is_file())
        report = json.loads((paper_dir / "report.json").read_text())
        self.assertEqual(report["status"], "ok")

    def test_repair_round_fixes_errors(self) -> None:
        transport = mock.Mock(return_value=fake_response(self.document))
        validator = FakeValidatorModule([["bad field"], []])
        result = self.run_one(validator, transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.attempts, 2)
        # Repair message carried the validator error back to the model.
        second_call_messages = transport.call_args_list[1].kwargs["messages"]
        self.assertIn("bad field", second_call_messages[-1]["content"])

    def test_persistent_errors_archive_as_validator_errors(self) -> None:
        transport = mock.Mock(return_value=fake_response(self.document))
        validator = FakeValidatorModule([["e"], ["e"], ["e"], ["e"]])
        result = self.run_one(validator, transport)
        self.assertEqual(result.status, "validator_errors")
        self.assertEqual(result.attempts, 3)  # initial + 2 repair rounds

    def test_cjk_only_finding_is_warning_status(self) -> None:
        document = {"extraction": {"status": "no_candidates", "summary": "中文"}}
        transport = mock.Mock(return_value=fake_response(document))
        validator = FakeValidatorModule([[], [], []])
        result = self.run_one(validator, transport)
        self.assertEqual(result.status, "ok_with_cjk_warnings")
        self.assertTrue(result.cjk_paths)

    def test_transport_error_is_archived(self) -> None:
        transport = mock.Mock(side_effect=RuntimeError("boom"))
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "transport_error")
        self.assertIn("boom", result.error)


class ChatCompletionRawTest(unittest.TestCase):
    def _http_error(self, code: int) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            "https://example.invalid", code, "err", hdrs=None, fp=io.BytesIO(b"")
        )

    def test_retries_429_then_succeeds(self) -> None:
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"model": "m"}'
        with mock.patch(
            "stella.lit.llm_batch.urllib.request.urlopen",
            side_effect=[self._http_error(429), ok],
        ), mock.patch("stella.lit.llm_batch.time.sleep"):
            response = chat_completion_raw(
                api_key="k",
                base_url="https://example.invalid/v1",
                model="m",
                messages=[{"role": "user", "content": "hi"}],
            )
        self.assertEqual(response, {"model": "m"})

    def test_retries_remote_disconnect_then_succeeds(self) -> None:
        import http.client

        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"model": "m"}'
        with mock.patch(
            "stella.lit.llm_batch.urllib.request.urlopen",
            side_effect=[
                http.client.RemoteDisconnected("closed without response"),
                ok,
            ],
        ), mock.patch("stella.lit.llm_batch.time.sleep"):
            response = chat_completion_raw(
                api_key="k",
                base_url="https://example.invalid/v1",
                model="m",
                messages=[{"role": "user", "content": "hi"}],
            )
        self.assertEqual(response, {"model": "m"})

    def test_auth_error_raises_immediately(self) -> None:
        with mock.patch(
            "stella.lit.llm_batch.urllib.request.urlopen",
            side_effect=self._http_error(401),
        ):
            with self.assertRaises(urllib.error.HTTPError):
                chat_completion_raw(
                    api_key="k",
                    base_url="https://example.invalid/v1",
                    model="m",
                    messages=[{"role": "user", "content": "hi"}],
                )


if __name__ == "__main__":
    unittest.main()
