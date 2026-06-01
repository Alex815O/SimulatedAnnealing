import copy
import datetime
import json
import math
import sys
from random import Random

import constraints

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


hyperparam: dict = {"T_max": 100, "T_min": 10, "max_attemts": 10, "alpha": 0.95}


def read_input(file_path):
    with open(file_path) as json_file:
        data = json.load(json_file)
        print(file_path, " is used as input.")
        print("Top-level keys:", data.keys())
        return data


def generate_neighbour(solution, input_data):
    jobs_nr = len(solution)

    for tries in range(100):
        neighbour = copy.deepcopy(solution)

        move_type = rand.choice(["swap_order", "change_machine"])

        if move_type == "swap_order":
            i = rand.randrange(jobs_nr)
            j = rand.randrange(jobs_nr)

            if i == j:
                continue

            neighbour[i], neighbour[j] = neighbour[j], neighbour[i]

        elif move_type == "change_machine":
            i = rand.randrange(jobs_nr)
            job_id = neighbour[i]["JobId"]

            ctx_job = next(job for job in input_data["Jobs"] if job["Id"] == job_id)
            eligible_machines = ctx_job["EligibleMachineIds"]

            # If there is only one eligible machine, this move cannot change anything.
            if len(eligible_machines) <= 1:
                continue

            current_machine = neighbour[i]["MachineId"]
            possible_machines = [m for m in eligible_machines if m != current_machine]

            if not possible_machines:
                continue

            neighbour[i]["MachineId"] = rand.choice(possible_machines)

        rebuilt = rebuild_schedule(neighbour, input_data)

        if rebuilt is not None and constraints.validate(rebuilt, input_data):
            return rebuilt

    # Fallback: no valid neighbour found.
    return copy.deepcopy(solution)


def evaluate(solution, input_data):
    sol_data = {"Jobs": copy.deepcopy(solution), "Feasible": True}
    tardiness = constraints.calculate_tardiness(input_data, sol_data)
    makespan = constraints.calculate_makespan(input_data, sol_data)
    return tardiness + makespan


def accept_neighbour(score_solution, score_neighbour, T):
    if score_neighbour < score_solution:
        return True

    probability = math.exp((score_solution - score_neighbour) / T)
    return rand.random() < probability


def simulated_annealing(input_data: dict):
    T = hyperparam["T_max"]
    T_min = hyperparam["T_min"]
    max_attempts = hyperparam["max_attemts"]
    alpha = hyperparam["alpha"]

    current = greedy_solution(input_data)
    current_score = evaluate(current, input_data)

    best = copy.deepcopy(current)
    best_score = current_score

    attempt = 0
    while T > T_min:
        for t in range(max_attempts):
            neighbour = generate_neighbour(current, input_data)
            neighbour_score = evaluate(neighbour, input_data)

            if accept_neighbour(current_score, neighbour_score, T):
                current = neighbour
                current_score = neighbour_score

            if current_score < best_score:
                best = copy.deepcopy(current)
                best_score = current_score

            log_result(best, best_score, T, t, attempt)
        attempt += 1
        T *= alpha

    return best


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


def greedy_solution(input_data):
    """
    Create an initial valid solution.

    Strategy:
    - sort jobs roughly by precedence count and due time
    - try different machine assignments
    - rebuild the schedule
    - return the first valid rebuilt schedule
    """

    input_jobs = {job["Id"]: job for job in input_data["Jobs"]}
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
        solution = make_solution_with_assignment(mode)
        rebuilt = rebuild_schedule(solution, input_data)

        if rebuilt is not None and constraints.validate(rebuilt, input_data):
            print(f"-------- greedy solution found using {mode} assignment --------")
            print(json.dumps(rebuilt, indent=4))
            print("----------------")
            return rebuilt

    # Then try random assignments
    for attempt in range(500):
        solution = make_solution_with_assignment("random", attempt)
        rebuilt = rebuild_schedule(solution, input_data)

        if rebuilt is not None and constraints.validate(rebuilt, input_data):
            print(
                f"-------- greedy solution found using random assignment, attempt {attempt} --------"
            )
            print(json.dumps(rebuilt, indent=4))
            print("----------------")
            return rebuilt

    raise RuntimeError("Could not construct a valid initial greedy solution.")


def log_result(solution, score, T, t, attemts):
    log_message = (
        f"[{timestamp}] "
        f"Attempt: {attemts:4d} | "
        f"t: {t:4d}             | "
        f"Temperature: {T:8.4f} | "
        f"Score: {score:10.4f}"
    )

    print(log_message)

    with open("sa_log.txt", "a") as f:
        f.write(f"{attemts},{T},{t}, {score},{timestamp}\n")


def main():

    if len(sys.argv) < 2:
        print("Usage: python simulated_anealing.py <input_file>")
        print("Default will be used:")
        input_path = "data/ToyInstance.json"
    else:
        input_path = sys.argv[1]
    input_data = read_input(input_path)

    best = simulated_annealing(input_data)

    print("-------- best solution found --------")
    print(json.dumps(best, indent=4))
    print("Valid:", constraints.validate(best, input_data))
    print("Score:", evaluate(best, input_data))
    print("----------------")


if __name__ == "__main__":
    main()
