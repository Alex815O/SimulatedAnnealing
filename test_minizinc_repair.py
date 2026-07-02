"""
Unit tests for the MiniZinc LNS repair model (lns_repair.mzn).

These are integration tests: they actually invoke MiniZinc/Chuffed through
`minizinc_repair.repair_with_minizinc` and assert that the model returns a
schedule which satisfies every constraint of the problem (checked with the
project's own validator in `constraints.validate`) and which honours the LNS
specific behaviour (frozen jobs must keep their fixed position).

Run with:
    python -m unittest test_minizinc_repair -v

The whole module is skipped automatically if the `minizinc` executable or the
Chuffed solver is not available on the machine.
"""

import copy
import json
import os
import shutil
import subprocess
import unittest

import constraints
import greedy
import minizinc_repair
import perprocessing


HERE = os.path.dirname(os.path.abspath(__file__))
TOY_INSTANCE_PATH = os.path.join(HERE, "data", "ToyInstance.json")
# A larger, resource-constrained instance for the real LNS scenario
# (only a small window of jobs is free, everything else is frozen).
LARGE_INSTANCE_PATH = os.path.join(HERE, "data", "PSSAI_PMS_j50_m5_r8_2.json")


def _minizinc_available() -> bool:
    """True only if both the minizinc binary and the Chuffed solver are usable."""
    if shutil.which("minizinc") is None:
        return False
    try:
        result = subprocess.run(
            ["minizinc", "--solvers"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and "chuffed" in result.stdout.lower()


MINIZINC_AVAILABLE = _minizinc_available()


def load_instance(path):
    """Load an instance and run the resource preprocessing the model needs."""
    with open(path) as f:
        instance = json.load(f)
    # build_minizinc_data reads context["ResourceEvents"], which is created here.
    return perprocessing.preprocessing(instance)


def load_toy_instance():
    return load_instance(TOY_INSTANCE_PATH)


def make_context(instance, frozen_positions=None):
    """
    Build a context_window for repair_with_minizinc.

    frozen_positions: optional {job_id: {"StartTime": int, "MachineId": int}}.
    Jobs listed there are frozen to that position, all other jobs are free.
    """
    frozen_positions = frozen_positions or {}
    context = copy.deepcopy(instance)
    for job in context["Jobs"]:
        if job["Id"] in frozen_positions:
            job["Frozen"] = True
            job["Position"] = frozen_positions[job["Id"]]
        else:
            job["Frozen"] = False
    return context


@unittest.skipUnless(
    MINIZINC_AVAILABLE, "minizinc binary and/or Chuffed solver not available"
)
class MiniZincRepairModelTest(unittest.TestCase):
    # Generous limit: the toy instance solves to optimality almost instantly,
    # but CI machines can be slow.
    TIME_LIMIT = 30

    @classmethod
    def setUpClass(cls):
        cls.instance = load_toy_instance()

    def repair(self, frozen_positions=None):
        context = make_context(self.instance, frozen_positions)
        solution = minizinc_repair.repair_with_minizinc(
            context, self.instance, time_limit_seconds=self.TIME_LIMIT
        )
        self.assertIsNotNone(
            solution,
            "repair_with_minizinc returned None: the model did not find a "
            "valid schedule for the toy instance.",
        )
        return solution

    # ------------------------------------------------------------------ #
    # Core: the model produces a feasible schedule for the whole instance #
    # ------------------------------------------------------------------ #

    def test_full_repair_produces_valid_solution(self):
        """With every job free, the model must return a fully feasible schedule."""
        solution = self.repair()

        # Every job is scheduled exactly once.
        job_ids = [item["JobId"] for item in solution]
        expected_ids = sorted(job["Id"] for job in self.instance["Jobs"])
        self.assertCountEqual(job_ids, expected_ids)
        self.assertEqual(len(job_ids), len(set(job_ids)), "a job was scheduled twice")

        # The project validator accepts the schedule (this is the definition of
        # "the model works as it should").
        self.assertTrue(
            constraints.validate(solution, self.instance),
            "constraints.validate rejected the schedule produced by MiniZinc.",
        )

    def test_machine_eligibility_respected(self):
        """Jobs are only ever placed on machines they are eligible for."""
        solution = self.repair()
        eligible = {
            job["Id"]: set(job["EligibleMachineIds"]) for job in self.instance["Jobs"]
        }
        for item in solution:
            self.assertIn(
                item["MachineId"],
                eligible[item["JobId"]],
                f"Job {item['JobId']} placed on ineligible machine "
                f"{item['MachineId']} (eligible: {sorted(eligible[item['JobId']])}).",
            )
        # Job 3 may only run on machine 1, Job 5 only on machine 2 (toy instance).
        by_id = {item["JobId"]: item for item in solution}
        self.assertEqual(by_id[3]["MachineId"], 1)
        self.assertEqual(by_id[5]["MachineId"], 2)

    def test_precedence_respected(self):
        """Predecessors must finish before their successors start."""
        solution = self.repair()
        by_id = {item["JobId"]: item for item in solution}
        for job in self.instance["Jobs"]:
            succ = by_id[job["Id"]]
            for pred_id in job["PrecedenceJobIds"]:
                pred = by_id[pred_id]
                pred_end = pred["StartTime"] + pred["ProcessingTime"]
                self.assertLessEqual(
                    pred_end,
                    succ["StartTime"],
                    f"Precedence violated: Job {pred_id} ends at {pred_end} but "
                    f"successor Job {job['Id']} starts at {succ['StartTime']}.",
                )

    def test_no_overlap_on_same_machine(self):
        """Two jobs on the same machine never overlap in time."""
        solution = self.repair()
        by_machine = {}
        for item in solution:
            by_machine.setdefault(item["MachineId"], []).append(item)
        for machine_id, items in by_machine.items():
            items = sorted(items, key=lambda it: it["StartTime"])
            for a, b in zip(items, items[1:]):
                a_end = a["StartTime"] + a["ProcessingTime"]
                self.assertLessEqual(
                    a_end,
                    b["StartTime"],
                    f"Jobs {a['JobId']} and {b['JobId']} overlap on machine "
                    f"{machine_id}.",
                )

    # ------------------------------------------------------------------ #
    # LNS specific behaviour: frozen jobs keep their fixed position        #
    # ------------------------------------------------------------------ #

    def test_frozen_jobs_keep_their_position(self):
        """
        Freeze a subset of jobs to the positions of a previously found feasible
        solution and check that the model leaves them exactly where they were,
        while still returning a globally valid schedule.
        """
        # 1) Get a feasible base schedule from the model itself.
        base = self.repair()
        base_by_id = {item["JobId"]: item for item in base}

        # 2) Freeze jobs 1 and 2 to their base positions, free the rest.
        frozen_positions = {
            job_id: {
                "StartTime": base_by_id[job_id]["StartTime"],
                "MachineId": base_by_id[job_id]["MachineId"],
            }
            for job_id in (1, 2)
        }
        repaired = self.repair(frozen_positions)
        repaired_by_id = {item["JobId"]: item for item in repaired}

        # 3) Frozen jobs must be untouched.
        for job_id, pos in frozen_positions.items():
            self.assertEqual(
                repaired_by_id[job_id]["StartTime"],
                pos["StartTime"],
                f"Frozen job {job_id} changed its StartTime.",
            )
            self.assertEqual(
                repaired_by_id[job_id]["MachineId"],
                pos["MachineId"],
                f"Frozen job {job_id} changed its MachineId.",
            )

        # 4) The overall schedule is still feasible.
        self.assertTrue(
            constraints.validate(repaired, self.instance),
            "Schedule with frozen jobs was rejected by constraints.validate.",
        )


@unittest.skipUnless(
    MINIZINC_AVAILABLE, "minizinc binary and/or Chuffed solver not available"
)
class FrozenWindowRepairTest(unittest.TestCase):
    """
    Tests the actual LNS use case on a larger instance: a feasible base
    schedule is built, then *almost all* jobs are frozen and only a small
    contiguous window is left free for MiniZinc to reschedule.

    The model must:
    - leave every frozen job exactly where it was (StartTime + MachineId),
    - return a schedule that is still globally feasible,
    - schedule every job (frozen and free) exactly once.

    The base schedule is produced by the greedy constructor. It is feasible for
    both the Python validator and the MiniZinc model, so re-running with a window
    simply has to find at least the original schedule again. This mirrors the
    real SA loop, which also freezes a window of the current (greedy-derived)
    solution and asks MiniZinc to repair it.
    """

    # The window repairs only have a handful of free jobs, so they finish within
    # this budget thanks to free search and the tight repair horizon.
    TIME_LIMIT = 30

    @classmethod
    def setUpClass(cls):
        cls.instance = load_instance(LARGE_INSTANCE_PATH)
        # A feasible starting schedule to freeze around. greedy needs its own
        # copy because it mutates the context it is given.
        cls.base = greedy.greedy_solution(
            copy.deepcopy(cls.instance), cls.instance, log=False
        )
        assert constraints.validate(
            cls.base, cls.instance
        ), "greedy base schedule is not valid; cannot build frozen-window test"
        cls.base_by_id = {item["JobId"]: item for item in cls.base}
        cls.original_makespan = max(
            item["StartTime"] + item["ProcessingTime"] for item in cls.base
        )

    def ordered_base(self):
        return sorted(self.base, key=lambda it: (it["StartTime"], it["MachineId"]))

    def pick_window(self, window_size):
        """Pick `window_size` consecutive jobs (in start-time order) from the
        middle of the schedule, mimicking how the LNS selects a window."""
        ordered = self.ordered_base()
        start = max(0, (len(ordered) - window_size) // 2)
        window = ordered[start : start + window_size]
        return {it["JobId"] for it in window}

    def repair_with_window(self, window_ids):
        """Freeze every job that is not in window_ids to its base position."""
        context = copy.deepcopy(self.instance)
        for job in context["Jobs"]:
            if job["Id"] in window_ids:
                job["Frozen"] = False
            else:
                base = self.base_by_id[job["Id"]]
                job["Frozen"] = True
                job["Position"] = {
                    "StartTime": base["StartTime"],
                    "MachineId": base["MachineId"],
                }
        # Lower bound for the MiniZinc horizon (see calculate_horizon).
        context["RepairOriginalMakespan"] = self.original_makespan

        # Restrict the free jobs to the time span their original positions
        # occupy. This keeps the identity solution feasible and makes the search
        # fast (see WINDOW_LB / WINDOW_UB in lns_repair.mzn).
        free = [self.base_by_id[job_id] for job_id in window_ids]
        context["RepairWindowStart"] = min(it["StartTime"] for it in free)
        context["RepairWindowEnd"] = max(
            it["StartTime"] + it["ProcessingTime"] for it in free
        )

        solution = minizinc_repair.repair_with_minizinc(
            context, self.instance, time_limit_seconds=self.TIME_LIMIT
        )
        self.assertIsNotNone(
            solution,
            f"repair_with_minizinc returned None for a free window of "
            f"{sorted(window_ids)} (the original positions are a valid fallback, "
            f"so the model should always succeed).",
        )
        return solution

    def assert_frozen_unchanged(self, solution, window_ids):
        sol_by_id = {item["JobId"]: item for item in solution}
        # All jobs present exactly once.
        self.assertCountEqual(
            list(sol_by_id), [job["Id"] for job in self.instance["Jobs"]]
        )
        for job in self.instance["Jobs"]:
            job_id = job["Id"]
            if job_id in window_ids:
                continue
            base = self.base_by_id[job_id]
            got = sol_by_id[job_id]
            self.assertEqual(
                got["StartTime"],
                base["StartTime"],
                f"Frozen job {job_id} moved: StartTime {base['StartTime']} "
                f"-> {got['StartTime']}.",
            )
            self.assertEqual(
                got["MachineId"],
                base["MachineId"],
                f"Frozen job {job_id} moved: MachineId {base['MachineId']} "
                f"-> {got['MachineId']}.",
            )

    def test_single_free_job_rest_frozen(self):
        """Minimal window: 49 of 50 jobs frozen, only one job may move."""
        window_ids = self.pick_window(1)
        solution = self.repair_with_window(window_ids)
        self.assert_frozen_unchanged(solution, window_ids)
        self.assertTrue(
            constraints.validate(solution, self.instance),
            "Schedule with a single free job was rejected by constraints.validate.",
        )

    def test_small_window_rest_frozen(self):
        """Realistic LNS window: a handful of free jobs, everything else frozen."""
        window_size = 6
        window_ids = self.pick_window(window_size)
        # Sanity: the scenario really is "mostly frozen".
        frozen_count = len(self.instance["Jobs"]) - len(window_ids)
        self.assertGreaterEqual(frozen_count, 40)

        solution = self.repair_with_window(window_ids)
        self.assert_frozen_unchanged(solution, window_ids)
        self.assertTrue(
            constraints.validate(solution, self.instance),
            "Schedule with a small free window was rejected by constraints.validate.",
        )

    def test_40_frozen_10_free(self):
        """LNS window of 10 free jobs with the other 40 jobs frozen."""
        window_ids = self.pick_window(10)
        self.assertEqual(len(window_ids), 10)
        frozen_count = len(self.instance["Jobs"]) - len(window_ids)
        self.assertEqual(frozen_count, 40)

        solution = self.repair_with_window(window_ids)
        self.assert_frozen_unchanged(solution, window_ids)
        self.assertTrue(
            constraints.validate(solution, self.instance),
            "Schedule with 40 frozen / 10 free jobs was rejected by "
            "constraints.validate.",
        )

    def test_window_surrounded_by_frozen(self):
        """
        20 frozen jobs, then a free window of 10, then 20 more frozen jobs
        (in start-time order). The free window is sandwiched between frozen
        jobs on both sides in time, so the model has to reschedule it into a
        fixed gap.
        """
        ordered = self.ordered_base()
        before = ordered[:20]
        window = ordered[20:30]
        after = ordered[30:]
        window_ids = {it["JobId"] for it in window}

        # The scenario really is "frozen | free | frozen".
        self.assertEqual(len(before), 20)
        self.assertEqual(len(window_ids), 10)
        self.assertEqual(len(after), 20)

        solution = self.repair_with_window(window_ids)
        self.assert_frozen_unchanged(solution, window_ids)

        # Sanity: there are frozen jobs starting both before and after the
        # earliest/latest free job, i.e. the window really is enclosed in time.
        window_starts = [self.base_by_id[jid]["StartTime"] for jid in window_ids]
        frozen_starts = [
            self.base_by_id[it["JobId"]]["StartTime"]
            for it in before + after
        ]
        self.assertTrue(any(s < min(window_starts) for s in frozen_starts))
        self.assertTrue(any(s > max(window_starts) for s in frozen_starts))

        self.assertTrue(
            constraints.validate(solution, self.instance),
            "Schedule with a frozen|free|frozen layout was rejected by "
            "constraints.validate.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
