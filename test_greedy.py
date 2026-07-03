"""
Unit tests for the greedy constructor (greedy.py).

Pure Python, no MiniZinc needed. They pin down the property the constructor must
guarantee: *when it returns a schedule, that schedule is valid and complete*.

- build_valid is the fast, resource-aware first path. For every instance it must
  either return None (it could not place some job) or a schedule that
  constraints.validate accepts and that contains every job exactly once. It must
  never return an invalid or partial schedule.
- greedy_solution must return a valid, complete schedule for the small/medium
  instances (where a greedy schedule reliably exists) and finish quickly.

Run with:
    .venv/Scripts/python.exe -m unittest test_greedy -v
"""

import glob
import json
import os
import time
import unittest

import constraints
import greedy
import perprocessing


HERE = os.path.dirname(os.path.abspath(__file__))
ALL_INSTANCES = sorted(glob.glob(os.path.join(HERE, "data", "*.json")))
# Instances where a greedy schedule reliably exists and is found fast.
SMALL_MEDIUM = [
    p for p in ALL_INSTANCES
    if os.path.basename(p) == "ToyInstance.json"
    or any(t in os.path.basename(p) for t in ("_j10_", "_j50_"))
]


def load(path):
    with open(path) as f:
        return perprocessing.preprocessing(json.load(f))


def is_complete(solution, instance):
    ids = [item["JobId"] for item in solution]
    expected = [job["Id"] for job in instance["Jobs"]]
    return sorted(ids) == sorted(expected) and len(ids) == len(set(ids))


class BuildValidTest(unittest.TestCase):
    def test_build_valid_never_returns_invalid_or_partial(self):
        """For every instance: build_valid returns None or a valid, complete schedule."""
        for path in ALL_INSTANCES:
            with self.subTest(instance=os.path.basename(path)):
                instance = load(path)
                solution = greedy.build_valid(instance)
                if solution is None:
                    continue  # allowed: could not place some job
                self.assertTrue(
                    is_complete(solution, instance),
                    "build_valid returned an incomplete schedule.",
                )
                self.assertTrue(
                    constraints.validate(solution, instance),
                    "build_valid returned a schedule constraints.validate rejects.",
                )


class ResourceCriticalInstanceTest(unittest.TestCase):
    """
    build_valid must solve instances where some jobs are resource-critical (their
    resource window closes early) and precedence + large sequence-dependent setups
    would otherwise push them past that window. The resource-deadline ordering
    schedules those chains early. These instances used to make build_valid fail.
    """

    HARD_INSTANCES = [
        "PSSAI_PMS_j100_m7_r18_4.json",
        "PSSAI_PMS_j500_m8_r29_1.json",
    ]

    def test_build_valid_solves_resource_critical_instances(self):
        for name in self.HARD_INSTANCES:
            with self.subTest(instance=name):
                instance = load(os.path.join(HERE, "data", name))
                solution = greedy.build_valid(instance)
                self.assertIsNotNone(
                    solution, f"build_valid failed to solve {name}."
                )
                self.assertTrue(is_complete(solution, instance))
                self.assertTrue(constraints.validate(solution, instance))


class GreedySolutionTest(unittest.TestCase):
    def test_valid_and_complete_on_small_medium(self):
        """greedy_solution returns a valid, complete schedule quickly for
        small/medium instances (build_valid handles them, no slow fallback)."""
        for path in SMALL_MEDIUM:
            with self.subTest(instance=os.path.basename(path)):
                instance = load(path)
                t0 = time.time()
                solution = greedy.greedy_solution(instance, instance, log=False)
                elapsed = time.time() - t0
                self.assertTrue(is_complete(solution, instance))
                self.assertTrue(constraints.validate(solution, instance))
                self.assertLess(
                    elapsed, 10.0, f"greedy_solution was slow ({elapsed:.1f}s)."
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
