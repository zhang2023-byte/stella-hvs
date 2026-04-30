from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.title_classifier import LLMTitleClassifier, heuristic_title_decision  # noqa: E402


class TitleClassifierRulesTest(unittest.TestCase):
    def assert_label(self, title: str, label: str, *, include: bool) -> None:
        decision = heuristic_title_decision(title)
        self.assertEqual(decision.label, label, title)
        self.assertEqual(decision.include, include, title)

    def test_direct_high_velocity_star_titles(self) -> None:
        direct_titles = [
            "AN ALTERNATIVE ORIGIN FOR HYPERVELOCITY STARS",
            "Milky Way archaeology using RR Lyrae and type II Cepheids. II. High-velocity RR Lyrae stars",
            "Gaia DR3 high radial velocity stars: Genuine fast-moving objects or outliers?",
            "A census of HRV stars from Gaia DR3",
            "THE VELOCITY DISTRIBUTION OF HYPERVELOCITY STARS",
            "Systematic search for blue hyper-velocity stars from LAMOST survey",
            "Discovery of a nearby 1700 km s-1 star ejected from the Milky Way by Sgr A*",
            "Gaia EDR3 in 6D: Searching for unbound stars in the Galaxy",
            "The fastest stars in the Galaxy",
            "Core-collapse supernovae in binaries as the origin of galactic hyper-runaway stars",
            "The impact of the Galactic bar and the Large Magellanic Cloud on hypervelocity star trajectories",
        ]
        for title in direct_titles:
            with self.subTest(title=title):
                self.assert_label(title, "rule-related", include=True)

    def test_mechanism_and_origin_titles_become_no_clear_title_evidence(self) -> None:
        ambiguous_titles = [
            "Stellar Escape from Globular Clusters. I. Escape Mechanisms and Properties at Ejection",
            "Where do they come from? Identification of globular cluster escaped stars",
            "Hyper-velocity and tidal stars from binaries disrupted by a massive Galactic black hole",
            "Computer simulations of encounters between massive black holes and binaries",
            "Relativistic tidal separation of binary stars by supermassive black holes",
            "On stellar migration from Andromeda to the Milky Way",
            "Intermediate-mass black holes in binary-rich star clusters",
        ]
        for title in ambiguous_titles:
            with self.subTest(title=title):
                self.assert_label(title, "no-clear-title-evidence", include=False)

    def test_generic_astronomy_or_tools_stay_in_no_clear_title_evidence(self) -> None:
        ambiguous_titles = [
            "Galaxy formation and evolution",
            "emcee: The MCMC Hammer",
            "galpy: A Python Library for Galactic Dynamics",
            "Gaia Early Data Release 3. Summary of the contents and survey properties",
            "Joint inference from parallax and proper motions",
            "A catalogue of Galactic GEMS: Globular cluster Extra-tidal Mock Stars",
            "Intermediate-mass black holes in dwarf galaxies",
            "The impact of the Galactic bar and the Large Magellanic Cloud on stellar trajectories",
        ]
        for title in ambiguous_titles:
            with self.subTest(title=title):
                self.assert_label(title, "no-clear-title-evidence", include=False)


class LLMClassifierPayloadTest(unittest.TestCase):
    def test_llm_payload_includes_abstract(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        [
                                            {
                                                "arxiv_id": "2501.00001",
                                                "include": True,
                                                "confidence": 0.9,
                                                "reason": "abstract mentions high-velocity stars",
                                                "label": "llm-direct",
                                            }
                                        ]
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(request: object, timeout: int) -> FakeResponse:
            captured["payload"] = json.loads(request.data.decode("utf-8"))  # type: ignore[attr-defined]
            return FakeResponse()

        classifier = LLMTitleClassifier(
            api_key="test",
            base_url="https://example.test",
            model="test-model",
            thinking="enabled",
            reasoning_effort="high",
        )
        with patch("urllib.request.urlopen", fake_urlopen):
            decisions = classifier.classify_batch(
                [
                    {
                        "arxiv_id": "2501.00001",
                        "title": "A subtle stellar kinematics paper",
                        "abstract": "The abstract reports a high-velocity star candidate.",
                        "categories": ["astro-ph.GA"],
                    }
                ]
            )

        self.assertTrue(decisions["2501.00001"].include)
        self.assertEqual(captured["payload"]["thinking"], {"type": "enabled"})  # type: ignore[index]
        self.assertEqual(captured["payload"]["reasoning_effort"], "high")  # type: ignore[index]
        messages = captured["payload"]["messages"]  # type: ignore[index]
        user_message = messages[1]["content"]  # type: ignore[index]
        self.assertIn('"abstract": "The abstract reports a high-velocity star candidate."', user_message)
        self.assertIn("Use the title, abstract, and categories.", user_message)


if __name__ == "__main__":
    unittest.main()
