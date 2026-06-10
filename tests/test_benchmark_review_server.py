from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SCRIPT = ROOT / "scripts" / "serve_benchmark_review.py"
SPEC = importlib.util.spec_from_file_location("serve_benchmark_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
server_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server_module)

from stella_benchmark.models import ExpertIdentity  # noqa: E402
from stella_benchmark.review_site import build_review_site  # noqa: E402

DIGEST = "sha256:abc"


def minimal_alignment(arxiv_id: str) -> dict:
    return {
        "schema_version": "stella.hvs_benchmark.alignment.v1",
        "arxiv_id": arxiv_id,
        "generated_at": "2026-06-10T12:00:00",
        "alignment_digest": DIGEST,
        "paper": {"title": "Test", "month": "2026-01", "links": {}},
        "variants": [{"variant_id": "a", "status": "candidates_found", "candidate_count": 1}],
        "paper_status": {"values": {"a": "candidates_found"}, "agreement": True},
        "clusters": [],
        "recall_assists": {"uncovered_ecsv_rows": []},
        "consensus_spot_checks": [],
    }


def verdict_body(**overrides) -> dict:
    body = {
        "alignment_digest": DIGEST,
        "paper_status_verdict": {"verdict": "accept", "gold_status": "candidates_found"},
        "items": [
            {
                "item_id": "cluster-001",
                "kind": "candidate_presence",
                "cluster_id": "cluster-001",
                "verdict": "accept",
                "base_variant": "a",
            }
        ],
    }
    body.update(overrides)
    return body


class ReviewServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "benchmark"
        (cls.root / "alignment").mkdir(parents=True)
        (cls.root / "alignment" / "9999.00001.alignment.json").write_text(
            json.dumps(minimal_alignment("9999.00001")), encoding="utf-8"
        )
        build_review_site(cls.root)
        handler = partial(
            server_module.ReviewHandler,
            root=cls.root,
            expert=ExpertIdentity(id="wz", name="Will"),
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.05)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls._tmp.cleanup()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get_json(self, path: str) -> dict:
        with urllib.request.urlopen(self.url(path)) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.url(path),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_serves_review_page_and_alignment(self) -> None:
        with urllib.request.urlopen(self.url("/review/index.html")) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("Expert Review", response.read().decode("utf-8"))
        payload = self.get_json("/alignment/9999.00001.alignment.json")
        self.assertEqual(payload["alignment_digest"], DIGEST)

    def test_session_endpoint_returns_expert(self) -> None:
        payload = self.get_json("/api/session")
        self.assertEqual(payload["expert"]["id"], "wz")

    def test_post_persists_with_expert_stamp(self) -> None:
        status, payload = self.post_json("/api/verdicts/9999.00001", verdict_body())
        self.assertEqual(status, 200)
        self.assertTrue(payload["saved"])
        target = self.root / "adjudication" / "9999.00001.adjudication.json"
        saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(saved["expert"]["id"], "wz")
        self.assertEqual(saved["alignment_digest"], DIGEST)
        first_decided = saved["items"][0]["decided_at"]
        self.assertTrue(first_decided)

        # Unchanged items keep their decided_at on re-save.
        status, _ = self.post_json("/api/verdicts/9999.00001", verdict_body())
        self.assertEqual(status, 200)
        saved_again = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(saved_again["items"][0]["decided_at"], first_decided)

    def test_digest_mismatch_returns_409(self) -> None:
        status, payload = self.post_json(
            "/api/verdicts/9999.00001", verdict_body(alignment_digest="sha256:other")
        )
        self.assertEqual(status, 409)
        self.assertIn("digest", payload["error"])

    def test_invalid_verdicts_return_400(self) -> None:
        body = verdict_body()
        body["items"][0]["verdict"] = "not-a-verdict"
        status, payload = self.post_json("/api/verdicts/9999.00001", body)
        self.assertEqual(status, 400)
        self.assertIn("invalid verdicts", payload["error"])

    def test_unknown_paper_returns_404(self) -> None:
        status, _ = self.post_json("/api/verdicts/0000.00000", verdict_body())
        self.assertEqual(status, 404)

    def test_files_outside_root_are_not_served(self) -> None:
        outside = Path(self._tmp.name) / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(self.url("/../secret.txt"))
        self.assertIn(context.exception.code, (400, 404))


if __name__ == "__main__":
    unittest.main()
