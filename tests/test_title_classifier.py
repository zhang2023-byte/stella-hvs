from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from high_velocity_lit.title_classifier import heuristic_title_decision  # noqa: E402


class TitleClassifierRulesTest(unittest.TestCase):
    def assert_label(self, title: str, label: str) -> None:
        decision = heuristic_title_decision(title)
        self.assertEqual(decision.label, label, title)
        self.assertTrue(decision.include, title)

    def assert_rejected(self, title: str) -> None:
        decision = heuristic_title_decision(title)
        self.assertFalse(decision.include, title)

    def test_direct_high_velocity_star_titles(self) -> None:
        direct_titles = [
            "AN ALTERNATIVE ORIGIN FOR HYPERVELOCITY STARS",
            "Milky Way archaeology using RR Lyrae and type II Cepheids. II. High-velocity RR Lyrae stars",
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
                self.assert_label(title, "rule-direct")

    def test_weak_mechanism_and_origin_titles(self) -> None:
        weak_titles = [
            "Stellar Escape from Globular Clusters. I. Escape Mechanisms and Properties at Ejection",
            "Where do they come from? Identification of globular cluster escaped stars",
            "Hyper-velocity and tidal stars from binaries disrupted by a massive Galactic black hole",
            "Computer simulations of encounters between massive black holes and binaries",
            "Relativistic tidal separation of binary stars by supermassive black holes",
            "On stellar migration from Andromeda to the Milky Way",
            "Intermediate-mass black holes in binary-rich star clusters",
        ]
        for title in weak_titles:
            with self.subTest(title=title):
                self.assert_label(title, "rule-weak")

    def test_generic_astronomy_or_tools_are_rejected(self) -> None:
        rejected_titles = [
            "Galaxy formation and evolution",
            "emcee: The MCMC Hammer",
            "galpy: A Python Library for Galactic Dynamics",
            "Gaia Early Data Release 3. Summary of the contents and survey properties",
            "Joint inference from parallax and proper motions",
            "A catalogue of Galactic GEMS: Globular cluster Extra-tidal Mock Stars",
            "Intermediate-mass black holes in dwarf galaxies",
            "The impact of the Galactic bar and the Large Magellanic Cloud on stellar trajectories",
        ]
        for title in rejected_titles:
            with self.subTest(title=title):
                self.assert_rejected(title)


if __name__ == "__main__":
    unittest.main()
