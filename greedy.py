import copy
import datetime
import json
import math
import sys
from random import Random

from deepdiff import DeepDiff

import constraints
import greedy_frozen_jobs as greedyF

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


def greedy_solution(window, context=None, log=True):
    """
    Create an initial valid solution.

    Strategy:
    - sort jobs roughly by precedence count and due time
    - try different machine assignments
    - rebuild the schedule
    - return the first valid rebuilt schedule
    """
    input_data = window
    if context is None:
        context = window

    machines = [m["Id"] for m in input_data["Machines"]]

    # Base job order
    jobs_sorted = sorted(
        input_data["Jobs"],
        key=lambda job: (
            len(job["PrecedenceJobIds"]),
            job["DueTime"],
        ),
    )

    def make_solution_with_assignment(mode, attempt=0):
        solution = []

        machine_load_count = {m_id: 0 for m_id in machines}

        for job in jobs_sorted:
            eligible = job["EligibleMachineIds"]

            if mode == "first":
                machine_id = eligible[0]

            elif mode == "balanced":
                # Choose eligible machine with currently fewest assigned jobs
                machine_id = min(
                    eligible, key=lambda m_id: machine_load_count.get(m_id, 0)
                )

            elif mode == "random":
                machine_id = rand.choice(eligible)

            else:
                raise ValueError("Unknown mode")

            machine_load_count[machine_id] = machine_load_count.get(machine_id, 0) + 1

            solution.append(
                {
                    "JobId": job["Id"],
                    "StartTime": 0,
                    "MachineId": machine_id,
                    "ProcessingTime": job["ProcessingTime"],
                    "DueTime": job["DueTime"],
                }
            )

        return solution

    # Try deterministic strategies first
    for mode in ["balanced", "first"]:
        print(mode)
        solution = make_solution_with_assignment(mode)
        rebuilt = rebuild_schedule(solution, input_data)

        if rebuilt is not None and constraints.validate(rebuilt, context):
            if log:
                print(
                    f"-------- greedy solution found using {mode} assignment --------"
                )
                print(json.dumps(rebuilt, indent=4))
                print("----------------")
            return rebuilt

    # Try greed frozen, without frozen:
    frozen_jobs = []
    for job in context["Jobs"]:
        job["Frozen"] = False
        frozen_jobs.append(job)    
    context["Jobs"] = frozen_jobs

    for attempt in range(10):
        print("Greedy Frozen: ", attempt)
        solution = greedyF.greedy_solution(input_data, 0, -1, True)

        if constraints.validate(rebuilt, context):
            if log:
                print(
                    f"-------- greedy solution found using greed frozen assignment, attempt {attempt} --------"
                )
                print(json.dumps(rebuilt, indent=4))
                print("----------------")
            return rebuilt
        
    # Then try random assignments

    for attempt in range(10):
        print("Random: ", attempt)
        solution = make_solution_with_assignment("random", attempt)
        rebuilt = rebuild_schedule(solution, input_data)

        if rebuilt is not None and constraints.validate(rebuilt, context):
            if log:
                print(
                    f"-------- greedy solution found using random assignment, attempt {attempt} --------"
                )
                print(json.dumps(rebuilt, indent=4))
                print("----------------")
            return rebuilt

    raise RuntimeError("Could not construct a valid initial greedy solution.")


def rebuild_schedule(solution, input_data):
    """
    Recalculate start times for a solution.

    The solution list gives us:
    - the jobs
    - their machine assignments
    - their current order in the list

    This function rebuilds StartTime values from scratch while respecting:
    - precedence constraints
    - machine order and setup times
    - initial setup times
    - resource capacities
    """
    input_jobs = {job["Id"]: job for job in input_data["Jobs"]}
    input_job_ids = {job["Id"] for job in input_data["Jobs"]}

    # Reset start times. They should be calculated from scratch.
    for job in solution:
        job["StartTime"] = 0

    scheduled = {}  # job_id -> scheduled job
    rebuilt = []  # final rebuilt schedule
    remaining = copy.deepcopy(solution)

    # Safety bound to prevent infinite searching for a resource-feasible time.
    # This is not mathematically perfect, but good enough for now.
    total_processing_time = sum(job["ProcessingTime"] for job in input_data["Jobs"])
    max_setup_time = max(
        max(job["JobSetupTimes"]) if job["JobSetupTimes"] else 0
        for job in input_data["Jobs"]
    )
    horizon_limit = (
        total_processing_time * len(input_data["Jobs"])
        + max_setup_time * len(input_data["Jobs"])
        + 1000
    )

    while remaining:
        progress = False

        for job in remaining[:]:
            job_id = job["JobId"]
            ctx_job = input_jobs[job_id]
            machine_id = job["MachineId"]

            # Machine eligibility check.
            # If a neighbour assigned the job to an invalid machine, this solution cannot be rebuilt.
            if machine_id not in ctx_job["EligibleMachineIds"]:
                remaining.remove(job)
                return None

            # Only schedule this job once all predecessors have already been scheduled.]
            if not all(
                pred_id in scheduled
                for pred_id in ctx_job["PrecedenceJobIds"]
                if pred_id in input_job_ids
            ):
                continue

            # Earliest start due to precedences.
            start_time = 0
            for pred_id in ctx_job["PrecedenceJobIds"]:
                if pred_id not in input_job_ids:
                    continue
                pred = scheduled[pred_id]
                pred_ctx = input_jobs[pred_id]
                pred_end = pred["StartTime"] + pred_ctx["ProcessingTime"]
                start_time = max(start_time, pred_end)

            # Earliest start due to previous job on the same machine.
            previous_jobs_on_machine = [
                j for j in rebuilt if j["MachineId"] == machine_id
            ]

            if previous_jobs_on_machine:
                last_job = previous_jobs_on_machine[-1]
                last_job_id = last_job["JobId"]
                last_ctx = input_jobs[last_job_id]
                last_end = last_job["StartTime"] + last_ctx["ProcessingTime"]

                # Setup time for current job after last job.
                setup_time = ctx_job["JobSetupTimes"][last_job_id - 1]
                start_time = max(start_time, last_end + setup_time)
            else:
                # First job on this machine.
                start_time = max(start_time, ctx_job["InitialSetupTime"])

            # Resource-aware part:
            # If resources are not available at this start time, delay the job.
            while not resources_available_for_job(
                ctx_job, start_time, rebuilt, input_data, input_jobs
            ):
                start_time += 1

                if start_time > horizon_limit:
                    return None

            new_job = copy.deepcopy(job)
            new_job["StartTime"] = start_time
            new_job["ProcessingTime"] = ctx_job["ProcessingTime"]
            new_job["DueTime"] = ctx_job["DueTime"]

            rebuilt.append(new_job)
            scheduled[job_id] = new_job
            remaining.remove(job)
            progress = True

        if not progress:
            # Usually means precedence deadlock or impossible ordering.
            return None

    return rebuilt


def get_resource_capacity_at(resource, time):
    """
    Return available capacity of one resource at a given time.
    If time is outside all availability periods, capacity is 0.
    """
    for period in resource["AvailabilityPeriods"]:
        if period["Start"] <= time < period["End"]:
            return period["Capacity"]
    return 0


def get_used_resource_capacity(resource_id, time, scheduled_jobs, input_jobs):
    """
    Return how much capacity of resource_id is already used at a given time
    by jobs that have already been scheduled.
    """
    used_capacity = 0

    for scheduled_job in scheduled_jobs:
        job_id = scheduled_job["JobId"]
        job_data = input_jobs[job_id]

        start = scheduled_job["StartTime"]
        end = start + job_data["ProcessingTime"]

        if start <= time < end:
            for req in job_data["RequiredResources"]:
                if req["ResourceId"] == resource_id:
                    used_capacity += req["Capacity"]

    return used_capacity


def resource_check_times(start_time, end_time, scheduled_jobs, input_data, input_jobs):
    """
    calculates on which timestamp resource capacity needs to be checked
    """
    check_times = {start_time}

    for event in input_data["ResourceEvents"]["capacity_changes"]:
        if start_time < event < end_time:
            check_times.add(event)

    for scheduled_job in scheduled_jobs:
        s = scheduled_job["StartTime"]
        e = s + input_jobs[scheduled_job["JobId"]]["ProcessingTime"]
        if start_time < s < end_time:
            check_times.add(s)
        if start_time < e < end_time:
            check_times.add(e)

    return check_times


def resources_available_for_job(
    job_data, start_time, scheduled_jobs, input_data, input_jobs
):
    """
    Check whether all required resources are available for the whole duration
    of job_data if it starts at start_time.
    """
    # If job requires no resources, it is always resource-feasible.
    if not job_data["RequiredResources"]:
        return True

    end_time = start_time + job_data["ProcessingTime"]
    resources_by_id = {r["Id"]: r for r in input_data["Resources"]}

    check_times = resource_check_times(
        start_time, end_time, scheduled_jobs, input_data, input_jobs
    )
    for time in check_times:
        for req in job_data["RequiredResources"]:
            resource_id = req["ResourceId"]
            needed_capacity = req["Capacity"]

            resource = resources_by_id[resource_id]
            available_capacity = get_resource_capacity_at(resource, time)
            used_capacity = get_used_resource_capacity(
                resource_id, time, scheduled_jobs, input_jobs
            )

            if used_capacity + needed_capacity > available_capacity:
                return False

    return True
