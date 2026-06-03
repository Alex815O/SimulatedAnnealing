import copy
import datetime
import json

import constraints

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Greedy criteria for picking the next job out of the available set.
#   "spt" -> shortest processing time (default, as in the reference algorithm)
#   "due" -> earliest due time
#   "est" -> earliest possible start time on any eligible machine
GREEDY_CRITERIA = ("spt", "due", "est")

# Safety padding added on top of the schedule horizon estimate.
HORIZON_PADDING = 1000



# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def greedy_solution(context, log=True):

    flex_jobs, frozen_jobs = get_jobs(context)
    place_frozen(context, frozen_jobs)

    while len(flex_jobs) > 0:




def pick_best_job(flex_jobs, solution, context):
    input_jobs = {job["Id"]: job for job in context["Jobs"]}

    for job in flex_jobs:

        next_start_time =
        resource_available = resources_available_for_job(
            job,
            next_start_time,
            solution,
            context,
            input_jobs
        )
        if resource_available:
            return job


    return flex_jobs[-1]

def calc_next_start_time(job, pre_job)

def pick_best_machine(job, solution, context):
    return 0


def place_frozen(context, frozen_jobs):
    solution = []

    for job in frozen_jobs:
        start_time = job["Position"]["StartTime"]
        machine = job["Position"]["MachineId"]
        processing_time = job["ProcessingTime"]
        due_time = job["DueTime"]
        job_id = job["Id"]

        solution.append(
            {
                "JobId": job_id,
                "StartTime": start_time,
                "MachineId": machine,
                "ProcessingTime": processing_time,
                "DueTime": due_time
            }
        )
    return solution


def get_jobs(context):
    frozen_jobs = []
    flex_jobs = []
    for job in context["Jobs"]
        frozen = job["Frozen"]
        if frozen is not None and frozen == True:
            frozen_jobs.append(job)
        else:
            flex_jobs.append(job)
    return flex_jobs, frozen_jobs



def get_resource_capacity_at(resource, time):
    """
    Return available capacity of one resource at a given time.
    If time is outside all availability periods, capacity is 0.
    """
    for period in resource["AvailabilityPeriods"]:
        if period["Start"] <= time < period["End"]:
            return period["Capacity"]
    return 0


def get_used_resource_capacity(resource_id, time, scheduled_jobs, input_jobs):
    """
    Return how much capacity of resource_id is already used at a given time
    by jobs that have already been scheduled.
    """
    used_capacity = 0

    for scheduled_job in scheduled_jobs:
        job_id = scheduled_job["JobId"]
        job_data = input_jobs[job_id]

        start = scheduled_job["StartTime"]
        end = start + job_data["ProcessingTime"]

        if start <= time < end:
            for req in job_data["RequiredResources"]:
                if req["ResourceId"] == resource_id:
                    used_capacity += req["Capacity"]

    return used_capacity


def resource_check_times(start_time, end_time, scheduled_jobs, input_data, input_jobs):
    """
    calculates on which timestamp resource capacity needs to be checked
    """
    check_times = {start_time}

    for event in input_data["ResourceEvents"]["capacity_changes"]:
        if start_time < event < end_time:
            check_times.add(event)

    for scheduled_job in scheduled_jobs:
        s = scheduled_job["StartTime"]
        e = s + input_jobs[scheduled_job["JobId"]]["ProcessingTime"]
        if start_time < s < end_time:
            check_times.add(s)
        if start_time < e < end_time:
            check_times.add(e)

    return check_times


def resources_available_for_job(
    job_data, start_time, scheduled_jobs, input_data, input_jobs
):
    """
    Check whether all required resources are available for the whole duration
    of job_data if it starts at start_time.
    """
    # If job requires no resources, it is always resource-feasible.
    if not job_data["RequiredResources"]:
        return True

    end_time = start_time + job_data["ProcessingTime"]
    resources_by_id = {r["Id"]: r for r in input_data["Resources"]}

    check_times = resource_check_times(
        start_time, end_time, scheduled_jobs, input_data, input_jobs
    )
    for time in check_times:
        for req in job_data["RequiredResources"]:
            resource_id = req["ResourceId"]
            needed_capacity = req["Capacity"]

            resource = resources_by_id[resource_id]
            available_capacity = get_resource_capacity_at(resource, time)
            used_capacity = get_used_resource_capacity(
                resource_id, time, scheduled_jobs, input_jobs
            )

            if used_capacity + needed_capacity > available_capacity:
                return False

    return True
