import copy
import datetime
import json
import math
import sys
from pickletools import read_int4
from random import Random

# import matplotlib.patches as patches
# import matplotlib.pyplot as plt
import constraints

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


hyperparam: dict = {"T_max": 100, "T_min": 10, "max_attemts": 10**3, "alpha": 0.95}


def read_input(file_path):
    with open(file_path) as json_file:
        data = json.load(json_file)
        print(file_path, " is used as input.")
        return data


def generate_neighbour(solution, input):
    solution = copy.deepcopy(solution)
    jobs_nr = len(solution)

    neighbour = copy.deepcopy(solution)

    while not constraints.validate(neighbour, input):
        job_to_move = int(rand.random() * jobs_nr)
        job_to_switch = int(rand.random() * jobs_nr)

        neighbour = switch_jobs(neighbour, job_to_move, job_to_switch)

    return neighbour


def switch_jobs(solution, job_to_move, job_to_switch):
    solution[job_to_switch]["StartTime"], solution[job_to_move]["StartTime"] = (
        solution[job_to_move]["StartTime"],
        solution[job_to_switch]["StartTime"],
    )
    solution[job_to_switch]["MachineId"], solution[job_to_move]["MachineId"] = (
        solution[job_to_move]["MachineId"],
        solution[job_to_switch]["MachineId"],
    )
    solution[job_to_switch]["EndTime"], solution[job_to_move]["EndTime"] = (
        solution[job_to_move]["EndTime"],
        solution[job_to_switch]["EndTime"],
    )
    solution[job_to_switch]["DueTime"], solution[job_to_move]["DueTime"] = (
        solution[job_to_move]["DueTime"],
        solution[job_to_switch]["DueTime"],
    )
    return solution


def evaluate(solution, input):
    score = 0
    for job in solution:
        tradiness = max(0, job["EndTime"] - job["DueTime"])
        makespan = job["EndTime"]
        score += tradiness - makespan
    return score


def cooling_ration(T, t):
    return T * hyperparam["alpha"]


def accapt_neighbour(score_solution, score_neighbour, T):
    prob = math.e ** ((score_neighbour - score_solution) / T)
    return rand.random() < prob


def simulated_annealing(input: dict):
    T = hyperparam["T_max"]
    T_min = hyperparam["T_min"]
    max_attemts = hyperparam["T_min"]

    t = 0
    solution = greedy_solution(input)
    score_solution = evaluate(
        solution, input
    )  # the pseudo code has this line, but it does not realy make sens?
    while t <= max_attemts:
        while T > T_min:
            neighbour = generate_neighbour(solution, input)
            score_solution = evaluate(solution, input)
            score_neighbour = evaluate(neighbour, input)

            if score_solution < score_neighbour:
                solution = neighbour
            elif accapt_neighbour(score_solution, score_neighbour, T):
                solution = neighbour
        T = cooling_ration(T, t)
        t += 1
    return {}


def greedy_solution(input):
    """Simple greedy solution: schedule jobs in topological order, respecting all constraints."""
    input_jobs = {job["Id"]: job for job in input["Jobs"]}

    # Create solution jobs with initial values
    solution = [
        {
            "JobId": job["Id"],
            "StartTime": 0,
            "MachineId": job["EligibleMachineIds"][0],  # First eligible machine
            "EndTime": 0,
            "DueTime": job["DueTime"],
        }
        for job in input["Jobs"]
    ]

    # Sort by number of predecessors (topological-like order)
    solution.sort(key=lambda j: len(input_jobs[j["JobId"]]["PrecedenceJobIds"]))

    # Track last job per machine for setup times
    machine_last_job = {}  # machine_id -> last job on that machine

    for job in solution:
        job_id = job["JobId"]
        ctx_job = input_jobs[job_id]
        machine_id = job["MachineId"]

        start_time = 0

        # 1. Precedence: must start after all predecessors finish
        for pred_id in ctx_job["PrecedenceJobIds"]:
            pred_job = next(j for j in solution if j["JobId"] == pred_id)
            start_time = max(start_time, pred_job["EndTime"])

        # 2. Machine: after last job on machine + setup time
        if machine_id in machine_last_job:
            last_job = machine_last_job[machine_id]
            setup_time = ctx_job["JobSetupTimes"][last_job["JobId"] - 1]
            start_time = max(start_time, last_job["EndTime"] + setup_time)
        else:
            # First job on this machine: initial setup time
            start_time = max(start_time, ctx_job["InitialSetupTime"])

        job["StartTime"] = start_time
        job["EndTime"] = start_time + ctx_job["ProcessingTime"]
        machine_last_job[machine_id] = job

    return solution


# def show_statistic(solution):
#     if not solution:
#         print("No solution to display")
#         return

#     fig, ax = plt.subplots(figsize=(12, 6))

#     # Get unique machines and sort them
#     machines = sorted(set(job["MachineId"] for job in solution))
#     machine_to_y = {machine: i for i, machine in enumerate(machines)}

#     # Create color map for jobs
#     colors = plt.cm.tab20.colors

#     # Plot each job as a horizontal bar
#     for idx, job in enumerate(solution):
#         machine = job["MachineId"]
#         start = job["StartTime"]
#         end = job["EndTime"]
#         duration = end - start
#         y_pos = machine_to_y[machine]

#         color = colors[idx % len(colors)]
#         rect = patches.Rectangle(
#             (start, y_pos - 0.4),
#             duration,
#             0.8,
#             linewidth=1,
#             edgecolor="black",
#             facecolor=color,
#         )
#         ax.add_patch(rect)

#         # Add job ID label in the middle of the bar
#         if duration > 0:
#             ax.text(
#                 start + duration / 2,
#                 y_pos,
#                 f"Job {job.get('JobID', idx)}",
#                 ha="center",
#                 va="center",
#                 fontsize=8,
#             )

#     # Configure plot
#     ax.set_xlabel("Time", fontsize=12)
#     ax.set_ylabel("Machine", fontsize=12)
#     ax.set_title("Job Schedule - Gantt Chart", fontsize=14, fontweight="bold")
#     ax.set_yticks(range(len(machines)))
#     ax.set_yticklabels([f"Machine {m}" for m in machines])

#     # Add grid
#     ax.grid(True, axis="x", alpha=0.3)
#     ax.set_axisbelow(True)

#     plt.tight_layout()
#     plt.show()


def log_result(solution, score, T, attemts):
    log_message = (
        f"[{timestamp}] "
        f"Attempt: {attemts:4d} | "
        f"Temperature: {T:8.4f} | "
        f"Score: {score:10.4f}"
    )

    print(log_message)

    with open("sa_log.txt", "a") as f:
        f.write(f"{attemts},{T},{score},{timestamp}\n")


def main():

    if len(sys.argv) < 2:
        print("Usage: python simulated_anealing.py <input_file>")
        print("Default will be used:")
        input_path = "data/ToyInstance.json"
    else:
        input_path = sys.argv[1]
    input_data = read_input(input_path)
    simulated_annealing(input_data)


if __name__ == "__main__":
    main()
