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
    batch_structure_errors,
    enforce_pipeline_fields,
    find_cjk_strings,
    repair_feedback,
    route_errors,
    run_paper,
    scaffold_structure_errors,
    split_batches,
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


class BibFilterTest(unittest.TestCase):
    BIB = (
        "% master library\n"
        "@string{apj = {ApJ}}\n"
        "@ARTICLE{cited2020,\n  author = {A},\n  journal = apj,\n}\n"
        "@ARTICLE{uncited2019,\n  author = {B},\n}\n"
        "@ARTICLE{also_cited,\n  author = {C},\n}\n"
    )

    def test_cited_keys_parsing_handles_variants(self) -> None:
        from stella.benchmark.context_pack import extract_cited_keys

        keys, nocite = extract_cited_keys(
            ["We \\citep[e.g.][]{cited2020, also_cited} stars."]
        )
        self.assertEqual(keys, {"cited2020", "also_cited"})
        self.assertFalse(nocite)
        _, nocite_all = extract_cited_keys(["\\nocite{*}"])
        self.assertTrue(nocite_all)

    def test_filter_keeps_cited_and_string_blocks_with_real_lines(self) -> None:
        from stella.benchmark.context_pack import filter_bib_to_cited

        body, kept, total = filter_bib_to_cited(
            self.BIB, {"cited2020", "also_cited"}
        )
        self.assertEqual(total, 12)
        self.assertIn("1|% master library", body)          # header kept
        self.assertIn("2|@string{apj = {ApJ}}", body)      # @string kept
        self.assertIn("3|@ARTICLE{cited2020,", body)
        self.assertIn("10|@ARTICLE{also_cited,", body)     # physical number
        self.assertNotIn("uncited2019", body)
        self.assertIn("omitted: uncited", body)
        self.assertEqual(kept, 9)

    def test_pack_filters_bib_but_keeps_bbl_whole(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            paper_dir = make_paper_dir(workspace)
            source = paper_dir / "arxiv_source"
            (source / "library.bib").write_text(self.BIB, encoding="utf-8")
            (source / "paper.bbl").write_text(
                "\\bibitem{x} Everything stays.\n", encoding="utf-8"
            )
            (source / "paper.tex").write_text(
                "StarA \\cite{cited2020}.\n", encoding="utf-8"
            )
            context = pack_paper_context(
                workspace,
                "9901.00001",
                ["literature/9901.00001/catalog_tables/table-a.ecsv"],
            )
        by_path = {item.path.split("/")[-1]: item for item in context.files}
        self.assertEqual(by_path["library.bib"].kind, "bibliography_filtered")
        self.assertEqual(by_path["library.bib"].original_lines, 12)
        self.assertEqual(by_path["paper.bbl"].kind, "paper_text")
        self.assertIn("Everything stays.", context.text)
        self.assertNotIn("uncited2019", context.text)


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
        text = repair_feedback([f"e{i}" for i in range(200)], [], "scaffold")
        self.assertIn("200 total, showing 80", text)
        self.assertIn("NEVER renumber", text)


class StagedStructureTest(unittest.TestCase):
    def stub(self, n: int) -> dict:
        return {
            "identifiers": {
                "record_id": f"9901.00001:cand-{n:03d}",
                "paper_candidate_id": f"Star{n}",
                "gaia_source_id": "",
                "all": [{"value": f"Star{n}", "source_refs": []}],
            }
        }

    def test_valid_scaffold_passes(self) -> None:
        document = {
            "extraction": {"status": "candidates_found"},
            "method_chain": [],
            "candidates": [self.stub(1), self.stub(2)],
            "candidate_groups_considered": [],
        }
        self.assertEqual(scaffold_structure_errors(document, "9901.00001"), [])

    def test_scaffold_rejects_full_candidates_and_bad_ids(self) -> None:
        fat = self.stub(1)
        fat["core"] = {}
        document = {
            "extraction": {"status": "candidates_found"},
            "method_chain": [],
            "candidates": [fat, {"identifiers": {"record_id": "wrong"}}],
            "candidate_groups_considered": [],
        }
        errors = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("ONLY" in error for error in errors))
        self.assertTrue(any("cand-001" in error for error in errors))

    def test_scaffold_status_roster_consistency(self) -> None:
        document = {
            "extraction": {"status": "no_candidates"},
            "method_chain": [],
            "candidates": [self.stub(1)],
            "candidate_groups_considered": [],
        }
        errors = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("conflicts" in error for error in errors))

    def test_batch_checks_count_and_ids(self) -> None:
        stubs = [self.stub(1), self.stub(2)]
        good = {
            "candidates": [
                {"identifiers": {"record_id": "9901.00001:cand-001"}},
                {"identifiers": {"record_id": "9901.00001:cand-002"}},
            ]
        }
        self.assertEqual(batch_structure_errors(good, stubs), [])
        short = {"candidates": good["candidates"][:1]}
        self.assertTrue(batch_structure_errors(short, stubs))
        swapped = {"candidates": list(reversed(good["candidates"]))}
        self.assertTrue(batch_structure_errors(swapped, stubs))

    def test_split_batches(self) -> None:
        roster = [self.stub(i) for i in range(1, 11)]
        batches = split_batches(roster, 4)
        self.assertEqual([len(b) for b in batches], [4, 4, 2])

    def test_route_errors_separates_candidates_from_scaffold(self) -> None:
        scaffold_errors, candidate_errors = route_errors(
            [
                "$.candidates[3].core.x: bad value",
                "$.candidates[11].core.y: bad unit",
                "$.candidates: method step 'step-15' is used as direct producer",
                "$.method_chain[2]: summary required",
            ]
        )
        self.assertEqual(sorted(candidate_errors), [3, 11])
        self.assertEqual(len(scaffold_errors), 2)

    def test_route_errors_handles_dotted_pydantic_paths(self) -> None:
        # pydantic emits dotted paths; they must reach the owning batch,
        # not the scaffold (pilot-03: 451 such errors looped on scaffold).
        scaffold_errors, candidate_errors = route_errors(
            [
                "$.candidates.8.astrophysical_origin: Input should be a "
                "valid dictionary or instance of AstrophysicalOrigin",
                "$.candidates.18.inclusion_assessment.confidence_reason: "
                "Field required",
                "$.candidates.0.core.observed_phase_space.distance"
                ".source_refs.0.TextSourceRef.raw_value: Extra inputs are "
                "not permitted",
                "$.method_chain.3.id: String should match pattern",
            ]
        )
        self.assertEqual(sorted(candidate_errors), [0, 8, 18])
        self.assertEqual(len(scaffold_errors), 1)

    def test_scaffold_method_chain_guards(self) -> None:
        document = {
            "extraction": {"status": "candidates_found"},
            "method_chain": [
                {"id": "step-01", "step_type": "input_catalog"},
                {"id": "step-03b", "step_type": "velocity_calculation"},
                {"id": "step-03", "step_type": "velocity_calculation"},
                {"id": "step-02", "step_type": "velocity_calculation"},
                {
                    "id": "step-04",
                    "step_type": "orbit_integration",
                    "depends_on": ["step-09"],
                },
            ],
            "candidates": [self.stub(1)],
            "candidate_groups_considered": [],
        }
        errors = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("step-03b" in error for error in errors))
        self.assertTrue(any("ascending" in error for error in errors))
        self.assertTrue(
            any("'step-09'" in error and "earlier" in error for error in errors)
        )

    def test_scaffold_rejects_source_missing(self) -> None:
        # The pipeline packed the sources itself, so a model claiming
        # source_missing is factually wrong about its own input
        # (pilot-04/05: two papers dodged extraction this way).
        document = {
            "extraction": {"status": "source_missing"},
            "method_chain": [],
            "candidates": [],
            "candidate_groups_considered": [],
        }
        errors = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("source_missing" in error for error in errors))

    def test_method_chain_order_hint_is_stage_aware(self) -> None:
        document = {
            "extraction": {"status": "candidates_found"},
            "method_chain": [
                {"id": "step-02", "step_type": "input_catalog"},
                {"id": "step-01", "step_type": "sample_selection"},
            ],
            "candidates": [self.stub(1)],
            "candidate_groups_considered": [],
        }
        initial = scaffold_structure_errors(document, "9901.00001")
        self.assertTrue(any("renumber the ENTIRE chain" in e for e in initial))
        during_repair = scaffold_structure_errors(
            document, "9901.00001", repair=True
        )
        self.assertTrue(any("never renumber" in e for e in during_repair))

    def test_batch_rejects_unknown_method_refs(self) -> None:
        stubs = [self.stub(1)]
        record = {
            "identifiers": {"record_id": "9901.00001:cand-001"},
            "core": {
                "observed_phase_space": {
                    "radial_velocity": {"method_refs": ["step-03b"]}
                }
            },
        }
        errors = batch_structure_errors(
            {"candidates": [record]}, stubs, {"step-01", "step-02"}
        )
        self.assertTrue(any("step-03b" in error for error in errors))
        ok = batch_structure_errors(
            {"candidates": [record]}, stubs, {"step-03b"}
        )
        self.assertEqual(ok, [])


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
    ARXIV = "9901.00001"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        make_paper_dir(self.workspace)
        make_skill_files(self.workspace)
        self.run_dir = self.workspace / "run"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def stub(self, n: int) -> dict:
        return {
            "identifiers": {
                "record_id": f"{self.ARXIV}:cand-{n:03d}",
                "paper_candidate_id": f"Star{n}",
                "gaia_source_id": "",
                "all": [{"value": f"Star{n}", "source_refs": []}],
            }
        }

    def scaffold_doc(self, n: int, summary: str = "fine") -> dict:
        status = "candidates_found" if n else "no_candidates"
        return {
            "extraction": {"status": status, "summary": summary},
            "method_chain": [{"id": "step-01", "step_type": "input_catalog"}],
            "candidates": [self.stub(i) for i in range(1, n + 1)],
            "candidate_groups_considered": [],
        }

    def batch_reply(self, numbers: list[int]) -> dict:
        return {
            "candidates": [
                {"identifiers": {"record_id": f"{self.ARXIV}:cand-{n:03d}"},
                 "filled": True}
                for n in numbers
            ]
        }

    def run_one(self, validator, transport, request_extra=None) -> object:
        return run_paper(
            workspace=self.workspace,
            arxiv_id=self.ARXIV,
            run_dir=self.run_dir,
            api_key="k",
            base_url="https://example.invalid/v1",
            model="deepseek-v4-pro",
            prompt_version="abc1234",
            batch_size=2,
            max_repair_rounds=2,
            request_extra=request_extra,
            validator_module=validator,
            transport=transport,
        )

    def test_no_candidates_paper_needs_one_call(self) -> None:
        transport = mock.Mock(
            side_effect=[fake_response(self.scaffold_doc(0))]
        )
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.scaffold_attempts, 1)
        self.assertEqual(result.batch_count, 0)
        self.assertEqual(transport.call_count, 1)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(
            final["extraction"]["tooling"]["model_id"], "deepseek-v4-pro"
        )
        self.assertEqual(final["extraction"]["tooling"]["prompt_version"], "abc1234")

    def test_staged_flow_merges_batches(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(3)),
                fake_response(self.batch_reply([1, 2])),
                fake_response(self.batch_reply([3])),
            ]
        )
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.batch_count, 2)
        self.assertEqual(result.batch_calls, 2)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(len(final["candidates"]), 3)
        self.assertTrue(all(c.get("filled") for c in final["candidates"]))
        attempts = self.run_dir / self.ARXIV / "attempts"
        self.assertTrue((attempts / "scaffold-call-01.response.json").is_file())
        self.assertTrue((attempts / "batch-001-call-01.response.json").is_file())
        self.assertTrue((attempts / "batch-002-call-01.response.json").is_file())

    def test_targeted_repair_touches_only_owning_batch(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(3)),
                fake_response(self.batch_reply([1, 2])),
                fake_response(self.batch_reply([3])),
                fake_response(self.batch_reply([3])),  # repair of batch 2
            ]
        )
        validator = FakeValidatorModule(
            [["$.candidates[2].core.x: bad value"], []]
        )
        result = self.run_one(validator, transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.repair_rounds, 1)
        self.assertEqual(transport.call_count, 4)
        repair_messages = transport.call_args_list[3].kwargs["messages"]
        self.assertEqual(len(repair_messages), 4)
        self.assertIn("bad value", repair_messages[-1]["content"])
        # Batch repairs see the live method_chain — the scaffold may have
        # been repaired after the batch's original prompt was built.
        self.assertIn("CURRENT method_chain", repair_messages[-1]["content"])
        self.assertIn("step-01", repair_messages[-1]["content"])
        attempts = self.run_dir / self.ARXIV / "attempts"
        self.assertTrue((attempts / "batch-002-call-02.response.json").is_file())
        self.assertFalse((attempts / "batch-001-call-02.response.json").exists())

    def test_rejected_repair_is_retried_with_structure_feedback(self) -> None:
        # pilot-04: a repair reply dropped one record, the count check
        # silently discarded it, and the error plateau froze. The repair
        # must be retried with the structure errors added to the feedback.
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(2)),
                fake_response(self.batch_reply([1, 2])),
                fake_response(self.batch_reply([1])),  # repair drops cand-002
                fake_response(self.batch_reply([1, 2])),  # retried repair ok
            ]
        )
        validator = FakeValidatorModule(
            [["$.candidates[0].core.x: bad value"], []]
        )
        result = self.run_one(validator, transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_count, 4)
        retry_feedback = transport.call_args_list[3].kwargs["messages"][-1]
        self.assertIn("exactly 2 candidates", retry_feedback["content"])
        self.assertIn("bad value", retry_feedback["content"])
        report = json.loads(
            (self.run_dir / self.ARXIV / "report.json").read_text()
        )
        self.assertTrue(
            any("repair_rejected" in entry for entry in report["stage_log"])
        )

    def test_scaffold_prompt_forbids_source_missing_misuse(self) -> None:
        from stella.benchmark.extraction_run import build_scaffold_prompt

        prompt = build_scaffold_prompt(
            {"schema_version": "x"}, PackedContext(text="paper text")
        )
        self.assertIn("do not use status 'source_missing'", prompt)
        self.assertIn("identifiable subset", prompt)

    def test_truncated_batch_is_split_in_half(self) -> None:
        truncated = fake_response({})
        truncated["choices"][0] = {
            "message": {"content": '{"candidates": [{"identifiers": {'},
            "finish_reason": "length",
        }
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(2)),
                truncated,  # batch-001 (2 stubs) hits the output cap
                fake_response(self.batch_reply([1])),  # batch-001a
                fake_response(self.batch_reply([2])),  # batch-001b
            ]
        )
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_count, 4)
        self.assertEqual(result.batch_count, 2)  # final groups after split
        self.assertEqual(result.batch_calls, 3)  # orphaned call + two fills
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(len(final["candidates"]), 2)
        attempts = self.run_dir / self.ARXIV / "attempts"
        self.assertTrue((attempts / "batch-001a-call-01.response.json").is_file())
        self.assertTrue((attempts / "batch-001b-call-01.response.json").is_file())
        report = json.loads(
            (self.run_dir / self.ARXIV / "report.json").read_text()
        )
        self.assertTrue(
            any("split_for_truncation" in entry for entry in report["stage_log"])
        )

    def test_document_level_error_repairs_scaffold(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(2)),
                fake_response(self.batch_reply([1, 2])),
                fake_response(self.scaffold_doc(2, summary="repaired")),
            ]
        )
        validator = FakeValidatorModule(
            [["$.method_chain[0]: summary is required"], []]
        )
        result = self.run_one(validator, transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_count, 3)
        feedback = transport.call_args_list[2].kwargs["messages"][-1]["content"]
        self.assertIn("summary is required", feedback)
        self.assertIn("NEVER renumber", feedback)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        self.assertEqual(final["extraction"]["summary"], "repaired")

    def test_invalid_scaffold_structure_is_retried_with_feedback(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response({"not": "a scaffold"}),
                fake_response(self.scaffold_doc(0)),
            ]
        )
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.scaffold_attempts, 2)
        retry_messages = transport.call_args_list[1].kwargs["messages"]
        self.assertIn("missing the", retry_messages[-1]["content"])

    def test_cjk_in_scaffold_routes_to_scaffold_repair(self) -> None:
        transport = mock.Mock(
            side_effect=[
                fake_response(self.scaffold_doc(0, summary="\u4e2d\u6587\u6458\u8981")),
                fake_response(self.scaffold_doc(0, summary="english")),
            ]
        )
        result = self.run_one(FakeValidatorModule([[], []]), transport)
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(result.cjk_paths, [])

    def test_transport_error_is_archived(self) -> None:
        transport = mock.Mock(side_effect=RuntimeError("boom"))
        result = self.run_one(FakeValidatorModule([[]]), transport)
        self.assertEqual(result.status, "transport_error")
        self.assertIn("boom", result.error)
        report = json.loads(
            (self.run_dir / self.ARXIV / "report.json").read_text()
        )
        self.assertEqual(report["status"], "transport_error")

    def test_request_extra_reaches_transport_and_tooling(self) -> None:
        extra = {"provider": {"order": ["deepseek"]}}
        transport = mock.Mock(side_effect=[fake_response(self.scaffold_doc(0))])
        result = self.run_one(
            FakeValidatorModule([[]]), transport, request_extra=extra
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(transport.call_args.kwargs["extra_body"], extra)
        final = json.loads(
            (self.run_dir / self.ARXIV / "literature_hvs_candidates.json").read_text()
        )
        recorded = final["extraction"]["tooling"]["request_parameters"]
        self.assertEqual(recorded["provider"], {"order": ["deepseek"]})


class RunnerRoutingTest(unittest.TestCase):
    """build_request_extra in scripts/run_benchmark_extraction.py."""

    @classmethod
    def setUpClass(cls) -> None:
        import importlib.util

        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "run_benchmark_extraction.py"
        )
        spec = importlib.util.spec_from_file_location("bench_runner", script)
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    @staticmethod
    def args(**overrides):
        import argparse

        defaults = {
            "provider": None,
            "no_provider_pin": False,
            "fallback_model": None,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_known_models_pin_first_party_provider(self) -> None:
        extra = self.runner.build_request_extra(self.args(), "deepseek-v4-pro")
        self.assertEqual(extra, {"provider": {"order": ["deepseek"]}})
        extra = self.runner.build_request_extra(self.args(), "mimo-v2.5-pro")
        self.assertEqual(extra, {"provider": {"order": ["xiaomi"]}})

    def test_unknown_model_and_opt_out_have_no_pin(self) -> None:
        self.assertEqual(
            self.runner.build_request_extra(self.args(), "some-other-model"), {}
        )
        self.assertEqual(
            self.runner.build_request_extra(
                self.args(no_provider_pin=True), "deepseek-v4-pro"
            ),
            {},
        )

    def test_explicit_provider_and_fallback_models(self) -> None:
        extra = self.runner.build_request_extra(
            self.args(
                provider=["zhipu", "deepseek"],
                fallback_model=["mimo-v2.5-pro", "mimo-v2.5-pro"],
            ),
            "deepseek-v4-pro",
        )
        self.assertEqual(extra["provider"], {"order": ["zhipu", "deepseek"]})
        self.assertEqual(extra["models"], ["mimo-v2.5-pro"])


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

    def test_extra_body_merges_without_overriding_core_fields(self) -> None:
        ok = mock.MagicMock()
        ok.__enter__.return_value.read.return_value = b'{"model": "m"}'
        with mock.patch(
            "stella.lit.llm_batch.urllib.request.urlopen", return_value=ok
        ) as urlopen:
            chat_completion_raw(
                api_key="k",
                base_url="https://example.invalid/v1",
                model="m",
                messages=[{"role": "user", "content": "hi"}],
                extra_body={
                    "provider": {"order": ["deepseek"]},
                    "models": ["fallback-model"],
                    "model": "evil-override",
                },
            )
        sent = json.loads(urlopen.call_args[0][0].data.decode("utf-8"))
        self.assertEqual(sent["provider"], {"order": ["deepseek"]})
        self.assertEqual(sent["models"], ["fallback-model"])
        self.assertEqual(sent["model"], "m")  # explicit args win

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
