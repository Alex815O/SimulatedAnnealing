def validate(solution, context) -> bool:
    return (
        machine_eligibility(solution, context)
        and non_overlapping_jobs(solution, context)
        and job_precedences(solution, context)
        and setup_times(solution, context)
        and resource_requirements(solution, context)
    )


def machine_eligibility(solution, context) -> bool:
    for job in solution:
        jobId = job["JobId"]
        allowedMachines = context["Jobs"].find(lambda j: j["Id"] == jobId)[
            "EligibleMachineIds"
        ]
        if job["MachineId"] not in allowedMachines:
            return False
    return True


def non_overlapping_jobs(solution, context) -> bool:
    return False


def job_precedences(solution, context) -> bool:
    return False


def setup_times(solution, context) -> bool:
    return False


def resource_requirements(solution, context) -> bool:
    return False
