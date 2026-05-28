import json
import math
from random import Random

rand = Random()


def read_input(file_path):
    with open("data.json") as json_file:
        data = json.load(json_file)
        print(file_path, " is used as input.")
        return data


def generate_neighbour(solution, input):
    return None


def evaluate(solution, input):
    return -1


def cooling_ration(T, t):
    return T


def accapt_neighbour(score_solution, score_neighbour, T):
    prob = math.e ** ((score_neighbour - score_solution) / T)
    return rand.random() < prob


def simulated_anealing(
    input: dict,
    hyperparam: dict = {"T": 100, "T_min": 10, "max_attemts": 10**3},
):
    T = hyperparam["T"]
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
    return {}


def show_statistic(solution):
    return


def log_result(solution, score, T, attemts):
    print(solution, score, T, attemts)


def main():
    print("Let's goooo!")


if __name__ == "__main__":
    main()
