import copy
import datetime
import json
from random import Random

from deepdiff import DeepDiff

import constraints
import greedy_frozen_jobs as greedy
import minizinc_repair


class FrozenNeighbour:
    def __init__(self, hyperparam: dict) -> None:
        """
        Relevant hyperparam fields:
            window_size_min       -> lower bound for random/relative window size
            window_size_max       -> upper bound for random window size
            window_size_divident  -> divisor of jobs_nr for relative window size
            window_size           -> fixed window size
            window_size_strategy  -> random, fixed, relative
            attemts_for_neighbour -> number of tries to find a valid neighbour
        """
        self.timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.rand = Random()
        self.window_size_min = hyperparam.get("window_size_min", 3)
        self.window_size_max = hyperparam.get("window_size_max", 10)
        self.window_size_strategy = hyperparam.get("window_size_strategy", "relative")
        self.window_size_divident = hyperparam.get("window_size_divident", 2)
        self.my_window_size = hyperparam.get("window_size", 8)
        self.attemts_for_neighbour = hyperparam.get("attemts_for_neighbour", 10000)

    def generate_neighbour(self, solution, input_data):
        jobs_nr = len(solution)
        solution = sorted(solution, key=lambda s: (s["StartTime"], s["MachineId"]))
        for tries in range(self.attemts_for_neighbour):
            print(tries)
            wsize = self.window_size(jobs_nr)
            i = self.rand.randint(0, jobs_nr - 1 - wsize)
            j = i + wsize

            context_window, window_start_time = self.convert_new_context(
                solution, input_data, i, j
            )
            


            try:
                print("Calling MiniZinc repair...")

                neighbour = minizinc_repair.repair_with_minizinc(
                context_window,
                input_data,
                time_limit_seconds=3)

                print("MiniZinc repair returned:", neighbour is not None)
                
                if neighbour is None:
                    print("MiniZinc did not find a valid repair, trying greedy fallback")
                    neighbour = greedy.greedy_solution(
                        context_window,
                        window_start_time,
                        -1,
                        log=False
                    )

            
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

    def window_size(self, jobs_nr):
        if self.window_size_strategy == "random":
            return self.rand.randint(self.window_size_min, self.window_size_max)
        elif self.window_size_strategy == "relative":
            return self.rand.randint(
                self.window_size_min, jobs_nr // self.window_size_divident
            )
        elif self.window_size_strategy == "fixed":
            return self.my_window_size

        print("No WINDOW SIZE defined, default will be 5...fix that")
        return 5

    def convert_new_context(self, solution, context, i, j):
        """
        creates a new context which defines all jobs as frozen, which are not in
        the window i-j.
        """
        context = copy.deepcopy(context)
        job_window, window_start_time = self.jobs_in_range(solution, context, i, j)
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

    def jobs_in_range(self, solution, context, i, j):
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
