import copy
import csv
import glob
import json
import os
import statistics
import time
from random import Random

import constraints
import perprocessing
import simulated_anealing


def log_hyperparams(instance_path, input_data):
    """Write the hyperparameters actually used for this run into its sa_log.txt.

    Called after setup_run_dir() so it targets the run's own subfolder, and it
    reads the global hyperparam dict *after* the benchmark overrides are applied,
    so the log reflects exactly what ran (including T_max/T_min for this size).
    """
    jobs_nr = len(input_data["Jobs"])
    T_max, T_min = simulated_anealing.init_temperature(jobs_nr)

    header = (
        "=" * 60 + "\n"
        f"Instance: {os.path.basename(instance_path)}\n"
        f"Jobs: {jobs_nr}\n"
        f"Temperature schedule: T_max={T_max}, T_min={T_min}\n"
        f"Hyperparameters:\n{json.dumps(simulated_anealing.hyperparam, indent=2)}\n"
        + "=" * 60
    )
    print(header)
    with open(os.path.join(simulated_anealing.run_dir, "sa_log.txt"), "a") as f:
        f.write(header + "\n")


# Benchmark-friendly overrides for the global SA hyperparameters.
#
# The defaults in simulated_anealing.py are tuned for solution quality, not for
# throughput: with use_greedy_fallback=False a window that MiniZinc cannot
# repair is retried up to attemts_for_neighbour (30) times, each retry a full
# ~repair_time_limit_seconds (10s) solver call. A single neighbour could then
# take minutes with no visible progress -- which looks like a hang. For a
# benchmark we want every neighbour bounded to at most one MiniZinc call plus a
# cheap greedy fallback, so a run finishes in reasonable, predictable time.
BENCHMARK_HYPERPARAMS = {
    "repair_time_limit_seconds": 5,   # shorter per-repair solver budget
    "attemts_for_neighbour": 8,       # fewer retries per neighbour
    "use_greedy_fallback": True,      # never burn 30 retries on a hard window
}


def strip_solution(solution):
    """
    The validator/submission format only needs:
    JobId, StartTime, MachineId.
    """
    return {
        "Jobs": [
            {
                "JobId": job["JobId"],
                "StartTime": job["StartTime"],
                "MachineId": job["MachineId"],
            }
            for job in solution
        ]
    }


def solution_filename(instance_path, run_id=None):
    base = os.path.basename(instance_path)
    name = base.replace(".json", "")

    if run_id is None:
        return f"{name}.solution.json"

    return f"{name}_run{run_id}.solution.json"


def run_single_instance(instance_path, runs=5):
    print("=" * 80)
    print(f"Running instance: {instance_path}")
    print("=" * 80)

    scores = []
    runtimes = []
    best_solution = None
    best_score = None

    for run in range(1, runs + 1):
        print("-" * 80)
        print(f"Run {run}/{runs}: {instance_path}")
        print("-" * 80)

        start_time = time.time()

        # Each run gets its own subfolder under runs/ (instance + timestamp +
        # run id) so its sa_log.txt and graph never collide with other runs.
        simulated_anealing.setup_run_dir(instance_path, run)

        input_data = simulated_anealing.read_input(instance_path)
        input_data = perprocessing.preprocessing(input_data)

        # Record the hyperparameters used for this instance in the run's log.
        log_hyperparams(instance_path, input_data)

        solution = simulated_anealing.simulated_annealing(input_data)

        valid = constraints.validate(solution, input_data)
        score = simulated_anealing.evaluate(solution, input_data)

        runtime = time.time() - start_time

        if not valid:
            print(f"WARNING: invalid solution for {instance_path}, run {run}")
            continue

        print(f"Valid: {valid}")
        print(f"Score: {score}")
        print(f"Runtime: {runtime:.2f}s")

        scores.append(score)
        runtimes.append(runtime)

        os.makedirs("results", exist_ok=True)

        run_solution_path = os.path.join(
            "results", solution_filename(instance_path, run)
        )

        with open(run_solution_path, "w") as f:
            json.dump(strip_solution(solution), f, indent=4)

        if best_score is None or score < best_score:
            best_score = score
            best_solution = copy.deepcopy(solution)

        # Ctrl+C during annealing: the run above returned its best-so-far and it
        # has now been saved. Stop launching further runs of this instance.
        if simulated_anealing.interrupted:
            print("Interrupted -- saved this run's best solution; stopping.")
            break

    if not scores:
        return {
            "instance": os.path.basename(instance_path),
            "runs": 0,
            "avg_score": None,
            "best_score": None,
            "std_score": None,
            "avg_runtime": None,
            "status": "failed",
        }

    final_solution_path = os.path.join("results", solution_filename(instance_path))

    with open(final_solution_path, "w") as f:
        json.dump(strip_solution(best_solution), f, indent=4)

    return {
        "instance": os.path.basename(instance_path),
        "runs": len(scores),
        "avg_score": statistics.mean(scores),
        "best_score": min(scores),
        "std_score": statistics.stdev(scores) if len(scores) > 1 else 0,
        "avg_runtime": statistics.mean(runtimes),
        "status": "ok" if len(scores) == runs else "partial",
    }


def main():
    # Apply the benchmark-friendly overrides so no single neighbour can stall
    # the run for minutes (see BENCHMARK_HYPERPARAMS).
    simulated_anealing.hyperparam.update(BENCHMARK_HYPERPARAMS)
    print("Benchmark hyperparameter overrides:", BENCHMARK_HYPERPARAMS)

    instance_paths = sorted(glob.glob("data/PSSAI_PMS_j*.json"))

    if not instance_paths:
        print("No benchmark instances found in data/")
        return

    all_results = []

    for instance_path in instance_paths:
        result = run_single_instance(instance_path, runs=3)
        all_results.append(result)

        with open("benchmark_summary.csv", "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "instance",
                    "runs",
                    "avg_score",
                    "best_score",
                    "std_score",
                    "avg_runtime",
                    "status",
                ],
            )
            writer.writeheader()
            writer.writerows(all_results)

        # Stop the whole benchmark after a Ctrl+C, keeping everything computed so
        # far (this instance's partial results are already in the CSV above).
        if simulated_anealing.interrupted:
            print("Benchmark interrupted -- results so far are saved.")
            break

    print("=" * 80)
    print("Benchmark summary")
    print("=" * 80)

    for result in all_results:
        print(result)


if __name__ == "__main__":
    main()
