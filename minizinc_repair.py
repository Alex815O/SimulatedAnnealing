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

    data = build_minizinc_data(context_window)

    with tempfile.TemporaryDirectory() as tmpdir:
        data_path = os.path.join(tmpdir, "lns_data.json")

        with open(data_path, "w") as f:
            json.dump(data, f)

        cmd = [
            "minizinc",
            "--solver",
            "chuffed",
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
                timeout=time_limit_seconds + 2,
            )
        except subprocess.TimeoutExpired:
            return None

        if result.returncode != 0:
            print("MiniZinc error:")
            print(result.stderr)
            return None

        solution = parse_minizinc_json_output(result.stdout, context_window)

        if solution is None:
            return None

        if constraints.validate(solution, original_input_data):
            return solution

        return None


def build_minizinc_data(context):
    jobs = sorted(context["Jobs"], key=lambda j: j["Id"])
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

    return {
        "M": M,
        "J": J,
        "R": R,
        "T": T,
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
    }


def calculate_horizon(context, max_fixed_end):
    jobs = context["Jobs"]

    total_processing = sum(job["ProcessingTime"] for job in jobs)
    max_initial_setup = max((job["InitialSetupTime"] for job in jobs), default=0)
    max_setup = max(
        (setup for job in jobs for setup in job["JobSetupTimes"]),
        default=0
    )

    return max_fixed_end + total_processing + max_initial_setup + max_setup * len(jobs) + 10


def parse_minizinc_json_output(stdout, context):
    """
    The main MiniZinc model outputs JSON:
    {
      "Jobs": [
        {"JobId": 1, "StartTime": 0, "MachineId": 1}
      ]
    }
    """

    try:
        json_start = stdout.find("{")
        json_end = stdout.rfind("}") + 1

        if json_start == -1 or json_end == 0:
            print("Could not find JSON in MiniZinc output:")
            print(stdout)
            return None

        json_text = stdout[json_start:json_end]
        parsed = json.loads(json_text)

    except json.JSONDecodeError:
        print("Could not parse MiniZinc JSON output:")
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