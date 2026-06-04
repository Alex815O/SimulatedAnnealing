import copy
import datetime
import json

import constraints

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")



def greedy_solution(context, window_start, window_end, log=True):

    flex_jobs, frozen_jobs = get_jobs(context)
    solution = place_frozen(context, frozen_jobs)

    last_job_per_machine = calc_last_jobs_pre_machine(solution, context, window_start)

    while len(flex_jobs) > 0:
        best_job = pick_best_job(flex_jobs, solution, context, last_job_per_machine)
        best_machine, start = pick_best_machine(best_job, solution, context, last_job_per_machine)

        frozen_jobs.append(best_job)
        flex_jobs.remove(best_job)

        best_job["Frozen"] = True
        best_job["Position"] = {
            "StartTime": start,
            "MachineId": best_machine
        }

        placed = place_job(best_job, solution)

        last_job_per_machine[best_machine] = placed

    if log:
        print(json.dumps(solution, indent=4))
    if constraints.validate(solution, context):
        return solution
    raise RuntimeError("No solution found")


def pick_best_job(flex_jobs, solution, context, last_job_per_machine):
    input_jobs = {job["Id"]: job for job in context["Jobs"]}
    machine_ids =  { machine["Id"] for machine in context["Machines"]}
    scheduled_ids = {s["JobId"] for s in solution}

    ready_jobs = [j for j in flex_jobs if precedences_satisfied(j, scheduled_ids)]
    ready_jobs = sort_low_resource_first(ready_jobs)

    for job in ready_jobs:

        next_start_time_per_machine = calc_next_start_time(job, last_job_per_machine, solution)
        allowed_machines = job["EligibleMachineIds"]
        for machineId in machine_ids:
            if machineId not in allowed_machines:
                continue

            resource_available = resources_available_for_job(
                job,
                next_start_time_per_machine[machineId],
                solution,
                context,
                input_jobs
            )
            if resource_available:
                return job

    return ready_jobs[0]

def sort_low_resource_first(jobs):
    '''
    Sort the list of jobs, by resource capacity
    number of required resources * sum of all resource capcity
    This will always check resource intense jobs first
    '''
    return sorted(jobs, key=lambda job: len(job["RequiredResources"]) * sum([resource["Capacity"] for resource in job["RequiredResources"]]))

def calc_next_start_time(job, last_job_per_machine: dict, solution):

    start_time_per_machine = {}
    floor = precedence_floor(job, solution)

    for machineId, pre_job in last_job_per_machine.items():

        if pre_job is not None:
            setup_delay = setup_time_delay(job, pre_job)
            machine_start = setup_delay + endTime(pre_job)
        else:
            machine_start = job["InitialSetupTime"]

        start_time_per_machine[machineId] = max(machine_start, floor)

    return start_time_per_machine

def setup_time_delay(job: dict, pre_job: dict):
    setuptimes = job["JobSetupTimes"]
    return setuptimes[pre_job["JobId"]-1]

def endTime(pre_job):
    return pre_job["StartTime"] + pre_job["ProcessingTime"]

def precedences_satisfied(job, scheduled_ids):
    return all(p in scheduled_ids for p in job["PrecedenceJobIds"])

def precedence_floor(job, solution):
    if not job["PrecedenceJobIds"]:
        return 0
    end_by_id = {s["JobId"]: s["StartTime"] + s["ProcessingTime"] for s in solution}
    return max(end_by_id[p] for p in job["PrecedenceJobIds"])

def calc_last_jobs_pre_machine(solution, context, window_start):
    machines = context["Machines"]
    last_job_per_maching = { machine["Id"]: None for machine in machines}
    solution = sorted(solution, key=lambda job: (job["MachineId"], job["StartTime"]))
    for job in solution:
        end_time = job["StartTime"] + job["ProcessingTime"]
        start_time = job["StartTime"]
        if start_time < window_start and window_start < end_time:
            machineId = job["MachineId"]
            last_job_per_maching[machineId] = job
        elif end_time < window_start:
            machineId = job["MachineId"]
            last_job_per_maching[machineId] = job
            
    return last_job_per_maching


def pick_best_machine(job, solution, context, last_job_per_machine):
    machine_ids =  [ machine["Id"] for machine in context["Machines"] if machine["Id"] in job["EligibleMachineIds"] ]
    start_time_per_machine = calc_next_start_time(job, last_job_per_machine, solution)

    earlist_start = start_time_per_machine[machine_ids[0]]
    best_machine = machine_ids[0]
    for machine in machine_ids[1:]:
        start = start_time_per_machine[machine]
        if earlist_start > start:
            earlist_start = start
            best_machine = machine
        
    return best_machine, earlist_start


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

def place_job(job, solution):
    start_time = job["Position"]["StartTime"]
    machine = job["Position"]["MachineId"]
    processing_time = job["ProcessingTime"]
    due_time = job["DueTime"]
    job_id = job["Id"]

    entry = {
        "JobId": job_id,
        "StartTime": start_time,
        "MachineId": machine,
        "ProcessingTime": processing_time,
        "DueTime": due_time
    }
    solution.append(entry)
    return entry


def get_jobs(context):
    frozen_jobs = []
    flex_jobs = []
    for job in context["Jobs"]:
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
