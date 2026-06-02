import copy
import datetime
import json
from multiprocessing import context
from random import Random
from tracemalloc import start

from deepdiff import DeepDiff

import constraints
import greedy

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


def generate_neighbour(solution, input_data):
    jobs_nr = len(solution)

    for tries in range(10000):
        window_size = 10
        i = rand.randint(0, jobs_nr - 1 - window_size)
        # j = rand.randint(i + 2, jobs_nr - 1)
        j = i + window_size
        print("range", j - i, i, j)

        context_window = convert_new_context(solution, input_data, i, j)

        try:
            neighbour_window = greedy.greedy_solution(context_window)
        except RuntimeError:
            continue

        neighbour = replace_jobs_in_solution(solution, neighbour_window)

        if constraints.validate(neighbour, input_data):
            print("#" * 10)
            diff = DeepDiff(solution, neighbour, ignore_order=True)
            print(diff)
            print("#" * 10)
            return neighbour

    # Fallback: no valid neighbour found.
    return copy.deepcopy(solution)


def replace_jobs_in_solution(solution, neighbour_window):
    neighbour = []
    for job_sol in solution:
        job_nei = [j for j in neighbour_window if j["JobId"] == job_sol["JobId"]]
        if len(job_nei) == 0:
            neighbour.append(job_sol)
        else:
            neighbour.append(job_nei[0])
    return neighbour


def convert_new_context(solution, context, i, j):
    """
    creates a new context with reduced number of jobs, so the greedy algorithmn can be reused
    """
    context = copy.deepcopy(context)
    job_window, window_start_time = jobs_in_range(solution, context, i, j)
    for job in job_window:
        job["InitialSetupTime"] = window_start_time
    context_window = context
    context_window["Jobs"] = job_window
    return context_window


def jobs_in_range(solution, context, i, j):
    """
    Searchs for jobs, which are in range of the jobs on position i and j
    """
    solution = copy.deepcopy(solution)
    window_start_time = solution[i]["StartTime"]
    last_job = solution[j]
    window_end_time = last_job["StartTime"] + last_job["ProcessingTime"]

    window_jobs = []
    for sol in solution:
        if (
            sol["StartTime"] >= window_start_time
            and sol["StartTime"] + sol["ProcessingTime"] <= window_end_time
        ):
            job = [j for j in context["Jobs"] if j["Id"] == sol["JobId"]][0]
            window_jobs.append(job)
    return window_jobs, window_start_time


def generate_neighbour_old(solution, input_data):
    jobs_nr = len(solution)

    for tries in range(10000):
        neighbour = copy.deepcopy(solution)

        move_type = rand.choice(["swap_order", "swap_order", "change_machine"])
        print(tries, move_type)
        if move_type == "swap_order":
            neighbour = swap_order_on_same_machine(neighbour, input_data)
        elif move_type == "change_machine":
            neighbour = swap_machine(neighbour, input_data, jobs_nr)

        if neighbour is None:
            continue

        rebuilt = rebuild_schedule(neighbour, input_data)

        # if rebuilt is not None:
        #     diff = DeepDiff(solution, rebuilt, ignore_order=True)
        #     print(diff)

        if rebuilt is not None and constraints.validate(rebuilt, input_data):
            return rebuilt

    # Fallback: no valid neighbour found.
    return copy.deepcopy(solution)


def swap_order_on_same_machine(solution, context):
    jobs_of_machine = {}
    for job in solution:
        jobs_of_machine[job["MachineId"]] = job

    random_machine = rand.randint(
        1, len(context["Machines"])
    )  # MachinId startet mit 1 und es is dict, ned list

    jobs_of_rand_machine = jobs_of_machine[random_machine]
    jobs_nr_of_machine = len(jobs_of_rand_machine)
    i = rand.randrange(jobs_nr_of_machine)
    j = rand.randrange(jobs_nr_of_machine)

    if i == j:
        return None

    return switch_jobs(solution, i, j)


def switch_jobs(solution, job_to_move, job_to_switch):
    solution[job_to_switch]["StartTime"], solution[job_to_move]["StartTime"] = (
        solution[job_to_move]["StartTime"],
        solution[job_to_switch]["StartTime"],
    )
    solution[job_to_switch]["MachineId"], solution[job_to_move]["MachineId"] = (
        solution[job_to_move]["MachineId"],
        solution[job_to_switch]["MachineId"],
    )
    (
        solution[job_to_switch]["ProcessingTime"],
        solution[job_to_move]["ProcessingTime"],
    ) = (
        solution[job_to_move]["ProcessingTime"],
        solution[job_to_switch]["ProcessingTime"],
    )
    solution[job_to_switch]["DueTime"], solution[job_to_move]["DueTime"] = (
        solution[job_to_move]["DueTime"],
        solution[job_to_switch]["DueTime"],
    )
    return solution


def swap_machine(solution, context, jobs_nr):
    i = rand.randrange(jobs_nr)
    job_id = solution[i]["JobId"]

    ctx_job = next(job for job in context["Jobs"] if job["Id"] == job_id)
    eligible_machines = ctx_job["EligibleMachineIds"]

    # If there is only one eligible machine, this move cannot change anything.
    if len(eligible_machines) <= 1:
        return None

    current_machine = solution[i]["MachineId"]
    possible_machines = [m for m in eligible_machines if m != current_machine]

    if not possible_machines:
        return None

    solution[i]["MachineId"] = rand.choice(possible_machines)
    return solution


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

            # Only schedule this job once all predecessors have already been scheduled.
            if not all(
                pred_id in scheduled and pred_id in solution["JobId"]
                for pred_id in ctx_job["PrecedenceJobIds"]
            ):
                continue

            # Earliest start due to precedences.
            start_time = 0
            for pred_id in ctx_job["PrecedenceJobIds"]:
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
