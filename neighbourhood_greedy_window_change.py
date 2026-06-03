import copy
import datetime
from random import Random

from deepdiff import DeepDiff

import constraints
import greedy

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


def generate_neighbour(solution, input_data):
    jobs_nr = len(solution)
    solution = sorted(solution, key=lambda s: (s["StartTime"], s["MachineId"]))
    for tries in range(10000):
        print(tries)
        window_size = 20
        i = rand.randint(0, jobs_nr - 1 - window_size)
        j = i + window_size

        context_window = convert_new_context(solution, input_data, i, j)

        try:
            neighbour_window = greedy.greedy_solution(context_window, log=False)
        except RuntimeError:
            print("not found")
            continue

        neighbour = replace_jobs_in_solution(solution, neighbour_window)

        if constraints.validate(neighbour, input_data):
            print("#" * 10)
            diff = DeepDiff(solution, neighbour, ignore_order=True)
            print(diff)
            print("#" * 10)
            if diff == {}:
                continue
            return neighbour
        else:
            print("not valid")

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
    job_window, _ = jobs_in_range(solution, context, i, j)
    job_window_ids = {j["Id"] for j in job_window}
    for job in job_window:
        job["PrecedenceJobIds"] = [
            j for j in job["PrecedenceJobIds"] if j in job_window_ids
        ]
        job["JobSetupTimes"] =
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
