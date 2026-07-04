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
    Only hand MiniZinc the window-relevant jobs; the rest keep their fixed
    position and are merged back into the solution after solving.

    context_window contains all jobs:
    - jobs outside the selected window have Frozen=True and Position fixed
    - jobs inside the window have Frozen=False
    """


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
            "-f",
            "--time-limit",
            str(time_limit_seconds * 1000),
            MODEL_PATH,
            data_path,
        ]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout = result.stdout
            stderr = result.stderr
            returncode = result.returncode
        except KeyboardInterrupt:
            print("KeyboardInterrupt")
            return None
        
        if returncode != 0:
            print("MiniZinc error:")
            print(stderr)
            return None

        solution = parse_minizinc_json_output(stdout, context_window)

        if solution is None:
            return None

        solution.extend(
            frozen_job_to_solution_entry(job) for job in dropped_frozen
        )

        if constraints.validate(solution, original_input_data):
            return solution

        return None


def select_relevant_jobs(context):
    """
    Reduce jobs which are not relevant for the repair of the defined window
    This reduce constraints -> which improves efficency

    A frozen job is kept only if it can actually interact with a free job:
      - its fixed interval overlaps the window , or
      - it is the direct machine predecessor/successor of the window on its
        machine 

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
            kept.append(job)
        else:
            non_overlapping_frozen.append(job)

    # Direct machine boundary neighbours of the window. 
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
        else:  
            best = successor.get(machine)
            if best is None or start < best["Position"]["StartTime"]:
                successor[machine] = job

    # finds first job on machine, that has special rules in the model
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

    # The main model has start[j] in 0..T-1.
    # If T is smaller than a frozen start time, MiniZinc becomes infeasible.
    T = max(T, max_fixed_end + 1)

    # Window the free jobs must be rescheduled into. 
    # We do not want to also check frozen jobs position
    window_lb = context.get("RepairWindowStart", 0)
    window_ub = context.get("RepairWindowEnd", T)
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