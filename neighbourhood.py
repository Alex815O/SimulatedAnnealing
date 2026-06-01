import copy
import datetime
from random import Random

import constraints

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


def generate_neighbour(solution, input_data):
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

        if rebuilt is not None and constraints.validate(rebuilt, input_data):
            print(rebuilt)
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
            if not all(pred_id in scheduled for pred_id in ctx_job["PrecedenceJobIds"]):
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


def resources_available_for_job(
    job_data, start_time, scheduled_jobs, input_data, input_jobs
):
    """
    Check whether all required resources are available for the whole duration
    of job_data if it starts at start_time.
    """
    processing_time = job_data["ProcessingTime"]
    end_time = start_time + processing_time

    # If job requires no resources, it is always resource-feasible.
    if not job_data["RequiredResources"]:
        return True

    resources_by_id = {r["Id"]: r for r in input_data["Resources"]}

    for t in range(start_time, end_time):
        for req in job_data["RequiredResources"]:
            resource_id = req["ResourceId"]
            needed_capacity = req["Capacity"]

            resource = resources_by_id[resource_id]
            available_capacity = get_resource_capacity_at(resource, t)
            used_capacity = get_used_resource_capacity(
                resource_id, t, scheduled_jobs, input_jobs
            )

            if used_capacity + needed_capacity > available_capacity:
                return False

    return True
