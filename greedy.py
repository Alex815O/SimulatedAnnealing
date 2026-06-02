import copy
import datetime
import json
import math
import sys
from random import Random

from deepdiff import DeepDiff

import constraints
import neighbourhood

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


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
        rebuilt = neighbourhood.rebuild_schedule(solution, input_data)

        if rebuilt is not None and constraints.validate(rebuilt, input_data):
            print(f"-------- greedy solution found using {mode} assignment --------")
            print(json.dumps(rebuilt, indent=4))
            print("----------------")
            return rebuilt

    # Then try random assignments

    print("-----start rebuild path -----------")
    for attempt in range(500):
        solution = make_solution_with_assignment("random", attempt)
        rebuilt = neighbourhood.rebuild_schedule(solution, input_data)

        if rebuilt is not None and constraints.validate(rebuilt, input_data):
            print(
                f"-------- greedy solution found using random assignment, attempt {attempt} --------"
            )
            print(json.dumps(rebuilt, indent=4))
            print("----------------")
            return rebuilt

    raise RuntimeError("Could not construct a valid initial greedy solution.")


def calculate_resource_change_events(resources):
    capacity_changes = []
    if R > 0:
        last_resource_timestamp = resources[0]["AvailabilityPeriods"][-1]["End"] + 1
        capacity_changes = sorted(
            {
                period["Start"]
                for resource in resources
                for period in resource["AvailabilityPeriods"]
            }.union({last_resource_timestamp}).union({T})
        )
    MAX_CAPACITY_CHANGE = len(capacity_changes)

    resourceCapacity = [
        [
            # Für jeden Zeitpunkt in capacity_changes
            # Finde die Kapazität der Ressource zu diesem Zeitpunkt
            next(
                period["Capacity"]
                for period in resource["AvailabilityPeriods"]
                if period["Start"] <= time < period["End"]
            )
            for time in capacity_changes[:-2]
        ]
        + [0]
        for resource in resources
    ]
