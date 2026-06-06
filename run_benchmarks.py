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

        input_data = simulated_anealing.read_input(instance_path)
        input_data = perprocessing.preprocessing(input_data)

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
            "results",
            solution_filename(instance_path, run)
        )

        with open(run_solution_path, "w") as f:
            json.dump(strip_solution(solution), f, indent=4)

        if best_score is None or score < best_score:
            best_score = score
            best_solution = copy.deepcopy(solution)

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

    final_solution_path = os.path.join(
        "results",
        solution_filename(instance_path)
    )

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
    instance_paths = sorted(glob.glob("data/PSSAI_PMS_*.json"))

    if not instance_paths:
        print("No benchmark instances found in data/")
        return

    all_results = []

    for instance_path in instance_paths:
        result = run_single_instance(instance_path, runs=1)
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

    print("=" * 80)
    print("Benchmark summary")
    print("=" * 80)

    for result in all_results:
        print(result)


if __name__ == "__main__":
    main()