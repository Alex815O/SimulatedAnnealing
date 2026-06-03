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
