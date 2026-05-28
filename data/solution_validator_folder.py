import argparse
import os
import subprocess


def find_matching_files(solution_folder, json_folder):
    solution_files = [
        f for f in os.listdir(solution_folder) if f.endswith(".solution.json")
    ]
    matching_files = []

    for solution_file in solution_files:
        base_name = solution_file.replace(".solution.json", "")
        json_file = f"{base_name}.json"
        if json_file in os.listdir(json_folder):
            matching_files.append(
                (
                    os.path.join(solution_folder, solution_file),
                    os.path.join(json_folder, json_file),
                )
            )

    return matching_files


def validate_solutions(solution_folder, json_folder):
    matching_files = find_matching_files(solution_folder, json_folder)

    for solution_file, json_file in matching_files:
        print(f"Validating {json_file} with {solution_file}")
        result = subprocess.run(
            [
                "python",
                "data//PSSAI_Topic_A_PMS_Instances//solution_validator.py",
                json_file,
                solution_file,
            ],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Validate solution files against their corresponding JSON files."
    )
    parser.add_argument(
        "solution_folder",
        type=str,
        help="Path to the folder containing solution files.",
    )
    parser.add_argument(
        "json_folder", type=str, help="Path to the folder containing JSON files."
    )

    args = parser.parse_args()

    validate_solutions(args.solution_folder, args.json_folder)


if __name__ == "__main__":
    main()
