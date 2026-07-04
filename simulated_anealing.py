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
# Set up via setup_run_dir() before the annealing starts.
run_dir = "."
# Name of the instance file currently being solved (without path/extension).
# Set in setup_run_dir(); used for the graph title/filename.
instance_name = ""


def setup_run_dir(input_path, run_id=None):
    """Create a unique subfolder under runs/ for this run's sa_log.txt and graph.

    Every run gets its own subfolder (instance name + timestamp + optional run
    id), so repeated or parallel runs never overwrite each other's logs/graphs.
    Also resets the live graph so each run starts a fresh curve titled with the
    instance file name.
    """
    global run_dir, instance_name
    instance_name = os.path.splitext(os.path.basename(input_path))[0]
    folder_timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = f"_run{run_id}" if run_id is not None else ""
    base = os.path.join("runs", f"{instance_name}_{folder_timestamp}{suffix}")

    # Guarantee uniqueness even when several runs start within the same second.
    run_dir = base
    counter = 1
    while os.path.exists(run_dir):
        run_dir = f"{base}_{counter}"
        counter += 1

    os.makedirs(run_dir, exist_ok=True)

    # Fresh graph per run, titled with the instance file name.
    visualize_logs.reset(instance_name)

    print(f"Run directory: {run_dir}")
    return run_dir


hyperparam: dict = {
    # --- Cooling schedule -----------------------------------------------------
    "alpha": 0.92,              
    "max_attemts": 5,           

    # --- LNS repair window (kept small so MiniZinc stays fast per neighbour) ---
    "window_size_strategy": "random",  # random|fixed|relative; random keeps MiniZinc small
    "window_size_min": 4,
    "window_size_max": 12,
    "window_size_divident": 2,  # only used by the "relative" strategy
    "window_size": 8,           # only used by the "fixed" strategy
    "attemts_for_neighbour": 30,
    "repair_time_limit_seconds": 8,
    "use_greedy_fallback": True,  # keep making progress when MiniZinc finds no repair

    # --- Neighbourhood selection ----------------------------------------------
    "small_instance_threshold": 1,  # <= this many jobs -> SingleChangeNeighbour
    "swap_order_weight": 2,          # SingleChangeNeighbour move mix
    "change_machine_weight": 1,
}

def init_temperature(jobs_nr):
    if jobs_nr <= 6:            
       return 5.0, 0.01
    elif jobs_nr <= 12:       
       return 300.0, 0.3
    elif jobs_nr <= 60:       
       return 5000.0, 5.0
    elif jobs_nr <= 200:      
       return 8000.0, 8.0
    else:                     
       return 15000.0, 15.0


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
    max_attempts = hyperparam["max_attemts"]
    alpha = hyperparam["alpha"]

    jobs_nr = len(input_data["Jobs"])
    neighbourhood = deceide_neighbourhood(jobs_nr)
    print("Neighbourhood class:", type(neighbourhood))
    print("Neighbourhood module:", type(neighbourhood).__module__)

    current = greedy.greedy_solution(input_data)
    current_score = evaluate(current, input_data)

    T, T_min = init_temperature(jobs_nr)
    
    print(f"Temperature schedule: T_max={T:.4f}, T_min={T_min:.4f} "
          f"(jobs={jobs_nr}, initial_score={current_score})")

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
        graph_file = os.path.join(
            run_dir, f"graph_{instance_name}_{score:.4f}_{timestamp}.png"
        )
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
