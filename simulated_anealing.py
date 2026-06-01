import copy
import datetime
import json
import math
import sys
from random import Random

import constraints
import neighbourhood

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


hyperparam: dict = {"T_max": 1000, "T_min": 10, "max_attemts": 10, "alpha": 0.95}


def read_input(file_path):
    with open(file_path) as json_file:
        data = json.load(json_file)
        print(file_path, " is used as input.")
        print("Top-level keys:", data.keys())
        return data


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
            neighbour = neighbourhood.generate_neighbour(current, input_data)
            neighbour_score = evaluate(neighbour, input_data)

            if accept_neighbour(current_score, neighbour_score, T):
                current = neighbour
                current_score = neighbour_score

            if current_score < best_score:
                best = copy.deepcopy(current)
                best_score = current_score

            log_result(best, current_score, T, t, attempt)
        attempt += 1
        T *= alpha

    return best


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
