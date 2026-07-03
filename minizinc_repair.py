import copy
import json
import os
import subprocess
import tempfile

import constraints


MODEL_PATH = os.path.join(os.path.dirname(__file__), "lns_repair.mzn")


def repair_with_minizinc(context_window, original_input_data, time_limit_seconds=3):
    """
    Repair a frozen/flexible LNS neighborhood using MiniZinc.

    context_window contains all jobs:
    - jobs outside the selected window have Frozen=True and Position fixed
    - jobs inside the window have Frozen=False
    """

    # Only hand MiniZinc the window-relevant jobs; the rest keep their fixed
    # position and are merged back into the solution after solving.
    kept_jobs, dropped_frozen = select_relevant_jobs(context_window)
    data = build_minizinc_data(context_window, kept_jobs)

    with tempfile.TemporaryDirectory() as tmpdir:
        data_path = os.path.join(tmpdir, "lns_data.json")

        with open(data_path, "w") as f:
            json.dump(data, f)

        cmd = [
            "minizinc",
            "--solver",
            "chuffed",
            # Free search: let Chuffed use its own activity-based search instead
            # of the static int_search annotation. On the LNS repair sub-problems
            # the static search fails to find even a feasible solution within the
            # time limit, while free search finds (and improves) one quickly.
            "-f",
            "--time-limit",
            str(time_limit_seconds * 1000),
            MODEL_PATH,
            data_path,
        ]

        # We pass --time-limit to MiniZinc, but Chuffed's free search does not
        # always honour it promptly (it can keep restarting well past the
        # limit). So we also enforce a hard wall-clock timeout here. Crucially,
        # when the process is killed we still keep whatever output it produced:
        # MiniZinc prints every improving solution as it goes, so the captured
        # output already contains the best solution found so far.
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=time_limit_seconds + 5,
            )
            stdout = result.stdout
            stderr = result.stderr
            returncode = result.returncode
        except subprocess.TimeoutExpired as exc:
            # On timeout subprocess kills the process and attaches the output it
            # had captured so far to the exception.
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            returncode = None

        # returncode 0 = solved/optimal, None = we killed it on timeout (but it
        # may still have printed a usable solution). Any other non-zero code is
        # a real MiniZinc error.
        if returncode not in (0, None):
            print("MiniZinc error:")
            print(stderr)
            return None

        solution = parse_minizinc_json_output(stdout, context_window)

        if solution is None:
            return None

        # MiniZinc only rescheduled the kept jobs; add the dropped frozen jobs
        # back at their fixed positions to rebuild the complete schedule.
        solution.extend(
            frozen_job_to_solution_entry(job) for job in dropped_frozen
        )

        if constraints.validate(solution, original_input_data):
            return solution

        return None


def select_relevant_jobs(context):
    """
    Reduce the jobs handed to MiniZinc to only those relevant to the repair
    window, so the sub-problem stays roughly window-sized instead of scaling with
    the whole instance.

    A free (non-frozen) job is always kept. A frozen job is kept only if it can
    actually interact with a free job:
      - its fixed interval overlaps the window (it competes for a machine or a
        resource while a free job runs), or
      - it is the direct machine predecessor/successor of the window on its
        machine (it constrains the setup time of the first/last window job there).
    Every other frozen job is dropped from the MiniZinc data and merged back into
    the solution unchanged afterwards (see repair_with_minizinc).

    With no window set (RepairWindowStart/End absent) the window is the whole
    horizon, so every frozen job overlaps and nothing is dropped -- identical to
    the previous "send the whole instance" behaviour.

    Returns (kept_jobs, dropped_frozen_jobs).
    """
    window_lb = context.get("RepairWindowStart", 0)
    window_ub = context.get("RepairWindowEnd", float("inf"))

    kept = []
    frozen_jobs = []
    non_overlapping_frozen = []

    for job in context["Jobs"]:
        if not job.get("Frozen", False):
            kept.append(job)
            continue

        frozen_jobs.append(job)
        pos = job["Position"]
        start = pos["StartTime"]
        end = start + job["ProcessingTime"]
        if start < window_ub and end > window_lb:
            # Frozen interval overlaps the window: keep it pinned so the model
            # still sees the machine/resource load it causes during the window.
            kept.append(job)
        else:
            non_overlapping_frozen.append(job)

    # Direct machine boundary neighbours of the window. A non-overlapping frozen
    # job either ends at/before window_lb (a predecessor candidate) or starts
    # at/after window_ub (a successor candidate). Only the closest one on each
    # side per machine can be the immediate neighbour of a window job and thus
    # constrain its setup time; keep those and drop the rest.
    predecessor = {}  # machine -> nearest frozen job ending <= window_lb
    successor = {}    # machine -> nearest frozen job starting >= window_ub
    for job in non_overlapping_frozen:
        pos = job["Position"]
        start = pos["StartTime"]
        end = start + job["ProcessingTime"]
        machine = pos["MachineId"]
        if end <= window_lb:
            best = predecessor.get(machine)
            if best is None or start > best["Position"]["StartTime"]:
                predecessor[machine] = job
        else:  # start >= window_ub
            best = successor.get(machine)
            if best is None or start < best["Position"]["StartTime"]:
                successor[machine] = job

    # The MiniZinc model exempts a job from its InitialSetupTime only if another
    # job on the same machine starts before it. If we drop every frozen job that
    # precedes a kept one, that kept job becomes "first on its machine" in the
    # sub-model and is forced to start >= its InitialSetupTime -- which its pinned
    # position may violate (it was not first in the full schedule), making the
    # model infeasible. So always keep the earliest-start frozen job on each
    # machine: it legitimately satisfies its own initial setup (the base is valid,
    # so the true first job respects it) and gives every later kept job on that
    # machine the predecessor it needs for the exemption.
    machine_first = {}
    for job in frozen_jobs:
        machine = job["Position"]["MachineId"]
        best = machine_first.get(machine)
        if best is None or job["Position"]["StartTime"] < best["Position"]["StartTime"]:
            machine_first[machine] = job

    must_keep_ids = {j["Id"] for j in predecessor.values()}
    must_keep_ids |= {j["Id"] for j in successor.values()}
    must_keep_ids |= {j["Id"] for j in machine_first.values()}

    dropped = []
    for job in non_overlapping_frozen:
        if job["Id"] in must_keep_ids:
            kept.append(job)
        else:
            dropped.append(job)

    return kept, dropped


def frozen_job_to_solution_entry(job):
    """Rebuild a solution entry for a frozen job from its fixed Position."""
    pos = job["Position"]
    return {
        "JobId": job["Id"],
        "StartTime": pos["StartTime"],
        "MachineId": pos["MachineId"],
        "ProcessingTime": job["ProcessingTime"],
        "DueTime": job["DueTime"],
    }


def build_minizinc_data(context, kept_jobs=None):
    if kept_jobs is None:
        kept_jobs, _ = select_relevant_jobs(context)
    jobs = sorted(kept_jobs, key=lambda j: j["Id"])
    machines = sorted(context["Machines"], key=lambda m: m["Id"])
    resources = sorted(context["Resources"], key=lambda r: r["Id"])

    J = len(jobs)
    M = len(machines)
    R = len(resources)

    jobsDuration = [job["ProcessingTime"] for job in jobs]
    jobsDueTime = [job["DueTime"] for job in jobs]
    initSetupTime = [job["InitialSetupTime"] for job in jobs]

    allowedMachines = []
    for job in jobs:
        allowedMachines.append([
            machine["Id"] in job["EligibleMachineIds"]
            for machine in machines
        ])

    requiredCapacity = []
    for job in jobs:
        row = []
        for resource in resources:
            capacity = next(
                (
                    req["Capacity"]
                    for req in job["RequiredResources"]
                    if req["ResourceId"] == resource["Id"]
                ),
                0
            )
            row.append(capacity)
        requiredCapacity.append(row)

    preJobs = []
    for job in jobs:
        row = []
        for pred in jobs:
            row.append(pred["Id"] in job["PrecedenceJobIds"])
        preJobs.append(row)

    setupTime = []
    for job in jobs:
        row = []
        for prev in jobs:
            row.append(job["JobSetupTimes"][prev["Id"] - 1])
        setupTime.append(row)

    is_frozen = []
    fixed_start = []
    fixed_machine = []

    max_fixed_end = 0

    for job in jobs:
        frozen = bool(job.get("Frozen", False))
        is_frozen.append(frozen)

        if frozen:
            start = job["Position"]["StartTime"]
            machine = job["Position"]["MachineId"]
            fixed_start.append(start)
            fixed_machine.append(machine)
            max_fixed_end = max(max_fixed_end, start + job["ProcessingTime"])
        else:
            fixed_start.append(0)
            fixed_machine.append(1)

    capacityChange = context["ResourceEvents"]["capacity_changes"]
    resourceCapacity = context["ResourceEvents"]["resource_capacity"]

    MAX_CAPACITY_CHANGE = len(capacityChange)

    T = calculate_horizon(context, max_fixed_end)

    # Important:
    # The main model has start[j] in 0..T-1.
    # If T is smaller than a frozen start time, MiniZinc becomes infeasible.
    T = max(T, max_fixed_end + 1)

    # Window the free jobs must be rescheduled into. When the caller knows the
    # window (the LNS neighbourhood does), restricting the free jobs to it keeps
    # the current solution feasible and makes the search dramatically faster.
    # Without it we fall back to the full horizon (no restriction).
    window_lb = context.get("RepairWindowStart", 0)
    window_ub = context.get("RepairWindowEnd", T)
    # Never tighter than the frozen-anchored horizon allows.
    window_ub = min(max(window_ub, window_lb), T)

    return {
        "M": M,
        "J": J,
        "R": R,
        "T": T,
        "WINDOW_LB": window_lb,
        "WINDOW_UB": window_ub,
        "MAX_CAPACITY_CHANGE": MAX_CAPACITY_CHANGE,
        "jobsDuration": jobsDuration,
        "jobsDueTime": jobsDueTime,
        "allowedMachines": allowedMachines,
        "requiredCapacity": requiredCapacity,
        "preJobs": preJobs,
        "initSetupTime": initSetupTime,
        "setupTime": setupTime,
        "capacityChange": capacityChange,
        "resourceCapacity": resourceCapacity,
        "is_frozen": is_frozen,
        "fixed_start": fixed_start,
        "fixed_machine": fixed_machine,
        "jobId": [job["Id"] for job in jobs],
    }


def calculate_horizon(context, max_fixed_end):
    jobs = context["Jobs"]

    repair_makespan = context.get("RepairOriginalMakespan")

    # LNS repair case: some jobs are frozen and we know the makespan of the
    # current solution. The current solution itself (every free job back at its
    # original position) is always a feasible repair, and it fits within that
    # makespan. So the makespan is already a sufficient horizon. Keeping it tight
    # is essential: a horizon several times larger than necessary blows up the
    # free jobs' start-time domains and makes MiniZinc search far too slow to
    # find any neighbour within the time limit.
    if repair_makespan is not None:
        return max(max_fixed_end, repair_makespan)

    # Full solve from scratch (no frozen jobs / no known makespan): reserve
    # enough room to place every job one after another, including initial and
    # worst-case inter-job setup times.
    free_processing = sum(job["ProcessingTime"] for job in jobs)
    max_initial_setup = max((job["InitialSetupTime"] for job in jobs), default=0)
    max_setup = max(
        (setup for job in jobs for setup in job["JobSetupTimes"]),
        default=0,
    )

    free_room = free_processing + max_initial_setup + max_setup * len(jobs)

    return max(max_fixed_end, free_room) + 10


def parse_minizinc_json_output(stdout, context):
    """
    The main MiniZinc model outputs JSON:
    {
      "Jobs": [
        {"JobId": 1, "StartTime": 0, "MachineId": 1}
      ]
    }

    When minimizing, MiniZinc prints EVERY improving solution, each as its own
    JSON block separated by a line of dashes ("----------"). We must take the
    LAST complete block (the best solution found); spanning from the first "{"
    to the last "}" would glue several blocks together into invalid JSON.
    """

    # Split on the solution separator and keep the last block that parses as the
    # expected JSON object. A block killed mid-print (no closing brace) simply
    # fails to parse and is ignored in favour of the previous complete one.
    parsed = None
    for block in stdout.split("----------"):
        start = block.find("{")
        end = block.rfind("}")
        if start == -1 or end == -1 or end < start:
            continue
        try:
            candidate = json.loads(block[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "Jobs" in candidate:
            parsed = candidate

    if parsed is None:
        print("Could not find a parseable solution in MiniZinc output:")
        print(stdout)
        return None

    jobs_by_id = {job["Id"]: job for job in context["Jobs"]}

    solution = []
    for item in parsed["Jobs"]:
        job_id = item["JobId"]
        job = jobs_by_id[job_id]

        solution.append({
            "JobId": job_id,
            "StartTime": item["StartTime"],
            "MachineId": item["MachineId"],
            "ProcessingTime": job["ProcessingTime"],
            "DueTime": job["DueTime"],
        })

    return solution