import copy
import datetime
import json
import math
import os
import sys
from operator import ne
from random import Random

import constraints
import greedy
import neighbourhood_single_change as SingleChangeNeihbour
import perprocessing
import visualize_logs
from neighbourhood_hybrid_lns import FrozenNeighbour
from neighbourhood_single_change import SingleChangeNeighbour

timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
rand = Random()

# Directory where the current run's sa_log.txt and graph are stored.
# Set up in main() via setup_run_dir() before the annealing starts.
run_dir = "."


def setup_run_dir(input_path):
    """Create a folder under runs/ named after the instance file and date."""
    global run_dir
    instance_name = os.path.splitext(os.path.basename(input_path))[0]
    folder_timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join("runs", f"{instance_name}_{folder_timestamp}")
    os.makedirs(run_dir, exist_ok=True)
    print(f"Run directory: {run_dir}")
    return run_dir


hyperparam: dict = {
    "T_max": 500,
    "T_min": 10,
    "max_attemts": 1,
    "alpha": 0.95,
    "window_size_min": 3,
    "window_size_max": 10,
    "window_size_divident": 2,
    "window_size": 5,
    "window_size_strategy": "random",
    "attemts_for_neighbour": 30,
    "small_instance_threshold": 0,
    "repair_time_limit_seconds": 10,
    "use_greedy_fallback": False
}


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

    jobs_nr = len(input_data["Jobs"])
    neighbourhood = deceide_neighbourhood(jobs_nr)
    print("Neighbourhood class:", type(neighbourhood))
    print("Neighbourhood module:", type(neighbourhood).__module__)

    current = greedy.greedy_solution(input_data)
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

    log_result(best, current_score, T, -1, -1, persist=True)
    return best


def deceide_neighbourhood(jobs_nr):
    if jobs_nr <= hyperparam["small_instance_threshold"]:
        print("Using SingleChangeNeighbour")
        return SingleChangeNeighbour(hyperparam)
    else:
        print("Using FrozenNeighbour.")
        return FrozenNeighbour(hyperparam)


def log_result(solution, score, T, t, attemts, persist=False):
    log_message = (
        f"[{timestamp}] "
        f"Attempt: {attemts:4d} | "
        f"t: {t:4d}             | "
        f"Temperature: {T:8.4f} | "
        f"Score: {score:10.4f}"
    )

    print(log_message)

    with open(os.path.join(run_dir, "sa_log.txt"), "a") as f:
        f.write(log_message + "\n")
    graph_file = None
    if persist:
        graph_file = os.path.join(run_dir, f"graph_{score:.4f}_{timestamp}.png")
    visualize_logs.update(score, T, graph_file)


def main():

    if len(sys.argv) < 2:
        print("Usage: python simulated_anealing.py <input_file>")
        print("Default will be used:")
        input_path = "data/ToyInstance.json"
    else:
        input_path = sys.argv[1]
    setup_run_dir(input_path)
    input_data = read_input(input_path)
    input_data = perprocessing.preprocessing(input_data)
    best = simulated_annealing(input_data)

    print("-------- best solution found --------")
    print(json.dumps(best, indent=4))
    print("Valid:", constraints.validate(best, input_data))
    print("Score:", evaluate(best, input_data))
    print("----------------")


if __name__ == "__main__":
    main()
