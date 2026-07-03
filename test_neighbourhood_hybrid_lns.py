"""
Unit tests for the LNS neighbourhood `FrozenNeighbour`
(neighbourhood_hybrid_lns.py).

These tests exercise the neighbourhood together with the *real* MiniZinc model:
`FrozenNeighbour` freezes every job outside a chosen window and asks
`minizinc_repair.repair_with_minizinc` to reschedule the window. Nothing is
mocked, so a passing run proves the whole "freeze everything but a window and
repair it with MiniZinc" pipeline works end to end.

They mirror the frozen-window cases in test_minizinc_repair.py, but drive them
through the neighbourhood's own window-selection / freezing logic instead of a
hand-built context.

Run with:
    python -m unittest test_neighbourhood_hybrid_lns -v

The module is skipped automatically if MiniZinc / Chuffed is not available.
"""

import copy
import unittest

import constraints
import greedy
import minizinc_repair
from neighbourhood_hybrid_lns import FrozenNeighbour

from test_minizinc_repair import (
    LARGE_INSTANCE_PATH,
    MINIZINC_AVAILABLE,
    load_instance,
)


def sorted_solution(solution):
    """Same ordering FrozenNeighbour.generate_neighbour uses internally."""
    return sorted(solution, key=lambda s: (s["StartTime"], s["MachineId"]))


def position_map(solution):
    return {item["JobId"]: (item["StartTime"], item["MachineId"]) for item in solution}


def changed_jobs(before, after):
    """JobIds whose start time or machine differ between two schedules."""
    a, b = position_map(before), position_map(after)
    return {job_id for job_id in a if job_id in b and a[job_id] != b[job_id]}


class WindowSelectionTest(unittest.TestCase):
    """
    get_job_window must always return in-bounds indices (0 <= i <= j <= jobs_nr-1),
    even when the configured window size is >= the number of jobs or the instance
    is tiny. A negative randint range here used to crash the whole SA run.
    """

    def _check_all_windows(self, hyperparam, jobs_counts, iterations=200):
        n = FrozenNeighbour(hyperparam)
        n.rand.seed(0)
        for jobs_nr in jobs_counts:
            for _ in range(iterations):
                wsize, i, j = n.get_job_window(jobs_nr)
                self.assertGreaterEqual(i, 0)
                self.assertLessEqual(i, j)
                self.assertLessEqual(j, jobs_nr - 1)
                self.assertEqual(j - i, wsize)

    def test_random_strategy_window_larger_than_instance(self):
        self._check_all_windows(
            {
                "window_size_strategy": "random",
                "window_size_min": 3,
                "window_size_max": 10,
            },
            jobs_counts=[1, 2, 3, 5, 10, 11],
        )

    def test_relative_strategy_small_instances(self):
        self._check_all_windows(
            {
                "window_size_strategy": "relative",
                "window_size_min": 3,
                "window_size_divident": 2,
            },
            jobs_counts=[1, 2, 3, 4, 5, 10],
        )

    def test_fixed_strategy_large_window(self):
        self._check_all_windows(
            {"window_size_strategy": "fixed", "window_size": 25},
            jobs_counts=[1, 5, 10, 30],
        )


@unittest.skipUnless(
    MINIZINC_AVAILABLE, "minizinc binary and/or Chuffed solver not available"
)
class FrozenNeighbourTest(unittest.TestCase):
    """
    A feasible greedy schedule is built once; the neighbourhood then has to
    repair windows of it. The greedy base is feasible for both the validator and
    the MiniZinc model, so a window repair always has at least the original
    positions as a fallback and must succeed.
    """

    # Repairs only have a handful of free jobs and are restricted to the window
    # time range, so they solve in a few seconds; this budget is plenty.
    TIME_LIMIT = 30

    @classmethod
    def setUpClass(cls):
        cls.instance = load_instance(LARGE_INSTANCE_PATH)
        # greedy's "balanced" strategy is deterministic; the copy is needed
        # because greedy mutates the context it is given.
        cls.base = greedy.greedy_solution(
            copy.deepcopy(cls.instance), cls.instance, log=False
        )
        assert constraints.validate(
            cls.base, cls.instance
        ), "greedy base schedule is not valid; cannot test the neighbourhood"
        cls.sorted_base = sorted_solution(cls.base)
        cls.job_ids = sorted(job["Id"] for job in cls.instance["Jobs"])

    def make_neighbour(self, hyperparam, seed=0):
        n = FrozenNeighbour(hyperparam)
        # Deterministic window selection.
        n.rand.seed(seed)
        return n

    # ------------------------------------------------------------------ #
    # Window-building logic (no solver): the right jobs get frozen.        #
    # ------------------------------------------------------------------ #

    def test_convert_new_context_freezes_outside_window(self):
        """
        convert_new_context must freeze every job outside the time window
        [start_i, end_j] to its current position and leave the window jobs free.
        """
        n = self.make_neighbour({})
        i, j = 20, 26
        context, window_start = n.convert_new_context(
            self.sorted_base, self.instance, i, j
        )

        base_pos = position_map(self.sorted_base)
        window_end = (
            self.sorted_base[j]["StartTime"] + self.sorted_base[j]["ProcessingTime"]
        )

        free_ids, frozen_ids = set(), set()
        for job in context["Jobs"]:
            if job["Frozen"]:
                frozen_ids.add(job["Id"])
                # Frozen jobs keep exactly their current position.
                start, machine = base_pos[job["Id"]]
                self.assertEqual(job["Position"]["StartTime"], start)
                self.assertEqual(job["Position"]["MachineId"], machine)
            else:
                free_ids.add(job["Id"])

        # The scenario is a genuine window: some jobs free, most frozen.
        self.assertGreater(len(free_ids), 0)
        self.assertGreater(len(frozen_ids), 0)
        self.assertEqual(free_ids | frozen_ids, set(self.job_ids))

        # Every free job really lies inside the window time range, and every
        # frozen job lies outside it.
        for job_id in free_ids:
            start, _ = base_pos[job_id]
            proc = next(
                it["ProcessingTime"]
                for it in self.sorted_base
                if it["JobId"] == job_id
            )
            self.assertGreaterEqual(start, window_start)
            self.assertLessEqual(start + proc, window_end)

        # The repair horizon anchor is the current makespan.
        expected_makespan = max(
            it["StartTime"] + it["ProcessingTime"] for it in self.sorted_base
        )
        self.assertEqual(context["RepairOriginalMakespan"], expected_makespan)

    # ------------------------------------------------------------------ #
    # Neighbourhood window + real model: frozen jobs stay put.             #
    # ------------------------------------------------------------------ #

    def repair_window(self, i, j):
        """Freeze everything outside [i, j] via the neighbourhood, then repair
        with the real MiniZinc model."""
        n = self.make_neighbour({})
        context, _ = n.convert_new_context(self.sorted_base, self.instance, i, j)

        frozen_positions = {
            job["Id"]: (job["Position"]["StartTime"], job["Position"]["MachineId"])
            for job in context["Jobs"]
            if job["Frozen"]
        }
        free_ids = {job["Id"] for job in context["Jobs"] if not job["Frozen"]}

        solution = minizinc_repair.repair_with_minizinc(
            context, self.instance, time_limit_seconds=self.TIME_LIMIT
        )
        self.assertIsNotNone(
            solution,
            f"MiniZinc repair returned None for window [{i}, {j}] "
            f"({len(free_ids)} free jobs); the original positions are a valid "
            f"fallback, so it should always succeed.",
        )
        return solution, frozen_positions, free_ids

    def assert_window_repair_ok(self, i, j):
        solution, frozen_positions, free_ids = self.repair_window(i, j)
        sol_pos = position_map(solution)

        # All jobs scheduled exactly once.
        self.assertCountEqual(list(sol_pos), self.job_ids)

        # Frozen jobs are untouched.
        for job_id, pos in frozen_positions.items():
            self.assertEqual(
                sol_pos[job_id],
                pos,
                f"Frozen job {job_id} moved during the window repair.",
            )

        # Only window (free) jobs may have changed.
        moved = changed_jobs(self.sorted_base, solution)
        self.assertTrue(
            moved <= free_ids,
            f"Jobs outside the window changed: {sorted(moved - free_ids)}.",
        )

        # The whole schedule is still feasible.
        self.assertTrue(
            constraints.validate(solution, self.instance),
            "Repaired schedule was rejected by constraints.validate.",
        )

    def test_repair_small_window(self):
        """A small neighbourhood window: only a few jobs are free."""
        self.assert_window_repair_ok(23, 26)

    def test_repair_medium_window(self):
        """A larger neighbourhood window, more free jobs to reschedule."""
        self.assert_window_repair_ok(20, 28)

    # ------------------------------------------------------------------ #
    # End to end: generate_neighbour produces a valid, window-local move.  #
    # ------------------------------------------------------------------ #

    def test_generate_neighbour_comes_from_minizinc(self):
        """
        generate_neighbour must return a valid, complete neighbour that was
        produced by MiniZinc (not the greedy fallback), and it must only touch a
        window of jobs - it never rebuilds the whole schedule.

        The greedy fallback is disabled, so the only way a (different) neighbour
        can be returned is if MiniZinc actually solved a window repair.
        """
        n = self.make_neighbour(
            {
                "window_size_strategy": "fixed",
                "window_size": 4,
                "attemts_for_neighbour": 8,
                "repair_time_limit_seconds": self.TIME_LIMIT,
                "use_greedy_fallback": False,
            },
            seed=1,
        )
        neighbour = n.generate_neighbour(self.base, self.instance)

        # The neighbour was produced by MiniZinc, not by greedy / the fallback.
        self.assertEqual(
            n.last_neighbour_source,
            "minizinc",
            "generate_neighbour did not return a MiniZinc-produced neighbour.",
        )

        # Valid and complete.
        self.assertCountEqual(
            [item["JobId"] for item in neighbour], self.job_ids
        )
        self.assertTrue(
            constraints.validate(neighbour, self.instance),
            "generate_neighbour returned an invalid schedule.",
        )

        # Frozen principle: only a window changed, not the whole schedule.
        moved = changed_jobs(self.base, neighbour)
        self.assertGreater(
            len(moved), 0, "MiniZinc neighbour is identical to the input."
        )
        self.assertLess(
            len(moved),
            len(self.base),
            "generate_neighbour changed every job; it should keep most frozen.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
