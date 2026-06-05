import copy
import datetime
from random import Random

import constraints
import greedy


class SingleChangeNeighbour:
    def __init__(self, hyperparam: dict) -> None:
        self.timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.rand = Random()
        self.attemts_for_neighbour = hyperparam.get("attemts_for_neighbour", 10000)
        self.swap_order_weight = hyperparam.get("swap_order_weight", 2)
        self.change_machine_weight = hyperparam.get("change_machine_weight", 1)

    def generate_neighbour(self, solution, input_data):
        jobs_nr = len(solution)
        move_pool = ["swap_order"] * self.swap_order_weight + [
            "change_machine"
        ] * self.change_machine_weight

        for tries in range(self.attemts_for_neighbour):
            neighbour = copy.deepcopy(solution)

            move_type = self.rand.choice(move_pool)
            print(tries, move_type)
            if move_type == "swap_order":
                neighbour = self.swap_order_on_same_machine(neighbour, input_data)
            elif move_type == "change_machine":
                neighbour = self.swap_machine(neighbour, input_data, jobs_nr)

            if neighbour is None:
                continue

            rebuilt = greedy.rebuild_schedule(neighbour, input_data)

            if rebuilt is not None and constraints.validate(rebuilt, input_data):
                return rebuilt

        # Fallback: no valid neighbour found.
        return copy.deepcopy(solution)

    def swap_order_on_same_machine(self, solution, context):
        indices_by_machine = {}
        for idx, job in enumerate(solution):
            indices_by_machine.setdefault(job["MachineId"], []).append(idx)

        swappable = [idxs for idxs in indices_by_machine.values() if len(idxs) >= 2]
        if not swappable:
            return None

        idxs = self.rand.choice(swappable)
        i, j = self.rand.sample(idxs, 2)

        solution[i], solution[j] = solution[j], solution[i]
        return solution

    def swap_machine(self, solution, context, jobs_nr):
        i = self.rand.randrange(jobs_nr)
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

        solution[i]["MachineId"] = self.rand.choice(possible_machines)
        return solution
