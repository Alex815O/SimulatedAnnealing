import copy
import datetime
from random import Random
import json

from deepdiff import DeepDiff

import constraints
import greedy_frozen_jobs as greedy

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


def generate_neighbour(solution, input_data):
    jobs_nr = len(solution)
    solution = sorted(solution, key=lambda s: (s["StartTime"], s["MachineId"]))
    for tries in range(10000):
        print(tries)
        window_size = 2
        i = rand.randint(0, jobs_nr - 1 - window_size)
        j = i + window_size

        context_window, window_start_time = convert_new_context(solution, input_data, i, j)

        try:
            neighbour = greedy.greedy_solution(context_window, window_start_time, -1, log=True)
        except RuntimeError:
            print("not found")
            continue


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


def convert_new_context(solution, context, i, j):
    """
    creates a new context which defines all jobs as frozen, which are not in
    the window i-j. 
    """
    context = copy.deepcopy(context)
    job_window, window_start_time = jobs_in_range(solution, context, i, j)
    job_window_ids = {j["Id"] for j in job_window}

    solution_by_job_id = {sol["JobId"]: sol for sol in solution}

    for job in context["Jobs"]:
        if job["Id"] not in job_window_ids:
            sol = solution_by_job_id[job["Id"]]
            job["Frozen"] = True
            job["Position"] = {
                "StartTime": sol["StartTime"],
                "MachineId": sol["MachineId"],
            }
        else:
            job["Frozen"] = False

    return context, window_start_time


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
