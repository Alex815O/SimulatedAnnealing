import copy
import datetime
import json
import math
import sys
from random import Random


import constraints
import greedy_frozen_jobs as greedyF

timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
rand = Random()


def greedy_solution(window, context=None, log=True):
    """
    Create an initial valid solution.

    Strategy:
    - sort jobs roughly by precedence count and due time
    - try different machine assignments
    - rebuild the schedule
    - return the first valid rebuilt schedule
    """
    input_data = window
    if context is None:
        context = window

    # Fastest path: a single-pass, resource-aware constructor. Quality is
    # irrelevant, only validity matters. Jobs are placed in precedence order, may
    # run concurrently up to resource capacity, and are delayed by jumping to the
    # next capacity/job event (never step by 1). Run it first (see build_valid).
    solution = build_valid(input_data)
    if solution is not None and constraints.validate(solution, context):
        if log:
            print("-------- greedy solution found using fast valid assignment --------")
            print(json.dumps(solution, indent=4))
            print("----------------")
        return solution

    machines = [m["Id"] for m in input_data["Machines"]]

    # Base job order
    jobs_sorted = sorted(
        input_data["Jobs"],
        key=lambda job: (
            len(job["PrecedenceJobIds"]),
            job["DueTime"],
        ),
    )

    def make_solution_with_assignment(mode, attempt=0):
        solution = []

        machine_load_count = {m_id: 0 for m_id in machines}

        for job in jobs_sorted:
            eligible = job["EligibleMachineIds"]

            if mode == "first":
                machine_id = eligible[0]

            elif mode == "balanced":
                # Choose eligible machine with currently fewest assigned jobs
                machine_id = min(
                    eligible, key=lambda m_id: machine_load_count.get(m_id, 0)
                )

            elif mode == "random":
                machine_id = rand.choice(eligible)

            else:
                raise ValueError("Unknown mode")

            machine_load_count[machine_id] = machine_load_count.get(machine_id, 0) + 1

            solution.append(
                {
                    "JobId": job["Id"],
                    "StartTime": 0,
                    "MachineId": machine_id,
                    "ProcessingTime": job["ProcessingTime"],
                    "DueTime": job["DueTime"],
                }
            )

        return solution

    # Try deterministic strategies first
    for mode in ["balanced", "first"]:
        print(mode)
        solution = make_solution_with_assignment(mode)
        rebuilt = rebuild_schedule(solution, input_data)

        if rebuilt is not None and constraints.validate(rebuilt, context):
            if log:
                print(
                    f"-------- greedy solution found using {mode} assignment --------"
                )
                print(json.dumps(rebuilt, indent=4))
                print("----------------")
            return rebuilt

    # Try greedy frozen, without frozen:
    for job in context["Jobs"]:
        job["Frozen"] = False

    for attempt in range(10):
        print("Greedy Frozen: ", attempt)

        try:
            solution = greedyF.greedy_solution(input_data, 0, -1, False)
        except RuntimeError:
            print("Greedy frozen failed, trying next attempt")
            continue

        if constraints.validate(solution, context):
            if log:
                print(
                    f"-------- greedy solution found using greedy frozen assignment, attempt {attempt} --------"
                )
                print(json.dumps(solution, indent=4))
                print("----------------")
            return solution
        
    # Then try random assignments

    for attempt in range(10):
        print("Random: ", attempt)
        solution = make_solution_with_assignment("random", attempt)
        rebuilt = rebuild_schedule(solution, input_data)

        if rebuilt is not None and constraints.validate(rebuilt, context):
            if log:
                print(
                    f"-------- greedy solution found using random assignment, attempt {attempt} --------"
                )
                print(json.dumps(rebuilt, indent=4))
                print("----------------")
            return rebuilt

    raise RuntimeError("Could not construct a valid initial greedy solution.")


def topological_order(jobs, key=None):
    """
    Return the jobs in a precedence-respecting (topological) order using Kahn's
    algorithm, so every predecessor comes before its successors. Precedence ids
    that are not part of `jobs` are ignored (e.g. when scheduling a sub-window).
    Returns None if the precedence graph has a cycle (no valid ordering exists).

    Among the jobs that are currently ready (all predecessors placed), the one
    with the smallest `key(job)` is emitted first (ties broken by Id). `key`
    defaults to the DueTime; build_valid passes a resource-deadline key so that
    jobs whose resource window closes early are scheduled first.
    """
    import heapq

    if key is None:
        key = lambda job: job["DueTime"]

    job_by_id = {job["Id"]: job for job in jobs}
    job_ids = set(job_by_id)

    # Predecessors restricted to the given job set.
    preds = {
        job["Id"]: [p for p in job["PrecedenceJobIds"] if p in job_ids]
        for job in jobs
    }
    indegree = {job_id: len(preds[job_id]) for job_id in job_ids}
    successors = {job_id: [] for job_id in job_ids}
    for job_id, plist in preds.items():
        for p in plist:
            successors[p].append(job_id)

    def entry(job_id):
        return (key(job_by_id[job_id]), job_id)

    ready = [entry(jid) for jid in job_ids if indegree[jid] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        _, job_id = heapq.heappop(ready)
        order.append(job_by_id[job_id])
        for succ in successors[job_id]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                heapq.heappush(ready, entry(succ))

    if len(order) != len(jobs):
        return None  # cycle
    return order


def resource_deadlines(input_data):
    """
    For each job, the latest start time at which it could still run with its
    required resources available (ignoring contention from other jobs),
    propagated backwards through precedence: a job's deadline is also bounded by
    every successor's deadline minus the job's processing time. Jobs whose
    resource window closes early therefore get an early deadline, and so do all
    of their precedence ancestors -- which is what lets build_valid place
    resource-critical chains early enough to fit their windows.

    A job with no required resources (and no constrained descendants) gets an
    infinite deadline (schedule it whenever). Returns {job_id: deadline}.
    """
    jobs = input_data["Jobs"]
    input_jobs = {job["Id"]: job for job in jobs}
    resources_by_id = {r["Id"]: r for r in input_data.get("Resources", [])}

    # Times where resource availability can change; the latest feasible start (if
    # any) always coincides with one of these.
    bounds = set()
    for resource in input_data.get("Resources", []):
        for period in resource["AvailabilityPeriods"]:
            bounds.add(period["Start"])
            bounds.add(max(0, period["End"] - 1))
    bounds = sorted(b for b in bounds if b >= 0)

    INF = float("inf")

    def own_deadline(job):
        if not job["RequiredResources"]:
            return INF
        latest = None
        for t in bounds:
            if all(
                get_resource_capacity_at(resources_by_id[req["ResourceId"]], t)
                >= req["Capacity"]
                for req in job["RequiredResources"]
            ):
                latest = t  # bounds are ascending, so keep the last feasible one
        return latest if latest is not None else -1  # -1: never feasible alone

    ids = set(input_jobs)
    preds = {j["Id"]: [p for p in j["PrecedenceJobIds"] if p in ids] for j in jobs}
    successors = {i: [] for i in ids}
    for i, plist in preds.items():
        for p in plist:
            successors[p].append(i)

    # Process successors before predecessors (reverse topological order).
    out_degree = {i: len(successors[i]) for i in ids}
    queue = [i for i in ids if out_degree[i] == 0]
    reverse_order = []
    while queue:
        i = queue.pop()
        reverse_order.append(i)
        for p in preds[i]:
            out_degree[p] -= 1
            if out_degree[p] == 0:
                queue.append(p)

    deadline = {}
    for i in reverse_order:
        d = own_deadline(input_jobs[i])
        for s in successors[i]:
            d = min(d, deadline[s] - input_jobs[i]["ProcessingTime"])
        deadline[i] = d
    return deadline


def _next_event_after(start, placed, input_data, input_jobs):
    """
    Smallest time strictly greater than `start` at which resource feasibility can
    change: a resource capacity change, or the start/end of an already-placed job
    (which frees or occupies shared capacity). Returns None if there is none.
    Used to delay a resource-blocked job by jumping instead of stepping by 1.
    """
    best = None

    def consider(t):
        nonlocal best
        if t > start and (best is None or t < best):
            best = t

    for t in input_data.get("ResourceEvents", {}).get("capacity_changes", []):
        consider(t)
    for pj in placed:
        s = pj["StartTime"]
        consider(s)
        consider(s + input_jobs[pj["JobId"]]["ProcessingTime"])
    return best


def _earliest_feasible_start(job, base_start, placed, input_data, input_jobs):
    """
    Earliest time >= base_start at which `job` can run without violating resource
    capacity, given the already-placed jobs (concurrency allowed). Delays the job
    by jumping to the next capacity/job event. Returns None if no such time is
    reachable (job needs more capacity than is ever available for its duration).
    """
    ctx_job = job
    if not ctx_job["RequiredResources"]:
        return base_start

    start = base_start
    # Bound the number of jumps to the number of distinct events plus a margin;
    # feasibility only changes at those events, so this can never miss a solution.
    max_jumps = (
        len(input_data.get("ResourceEvents", {}).get("capacity_changes", []))
        + 2 * len(placed)
        + 8
    )
    for _ in range(max_jumps + 1):
        if resources_available_for_job(
            ctx_job, start, placed, input_data, input_jobs
        ):
            return start
        nxt = _next_event_after(start, placed, input_data, input_jobs)
        if nxt is None:
            return None
        start = nxt
    return None


def build_valid(input_data):
    """
    Single-pass, resource-aware greedy constructor. Places jobs in a
    precedence-respecting order; each job may run concurrently with others up to
    the shared resource capacity, and is delayed by jumping to the next relevant
    event (not by stepping +1). For each job the eligible machine giving the
    earliest feasible start is chosen. Every hard constraint (eligibility,
    machine non-overlap, precedence, setup, resources) is satisfied by
    construction, so the result passes constraints.validate.

    Returns a solution list, or None if it cannot place some job (cyclic
    precedence, or a job needing more resource capacity than is ever available)
    -- in which case greedy_solution falls back to its other strategies.
    """
    jobs = input_data["Jobs"]
    input_jobs = {job["Id"]: job for job in jobs}

    # Schedule resource-critical jobs (and their precedence ancestors) first, so
    # jobs whose resource window closes early are placed while capacity is still
    # available instead of being pushed past their window by the schedule's
    # sequence-dependent-setup stretch.
    deadline = resource_deadlines(input_data)
    order = topological_order(
        jobs, key=lambda job: deadline.get(job["Id"], float("inf"))
    )
    if order is None:
        return None

    solution = []
    scheduled = {}  # job_id -> entry
    jobs_on_machine = {}  # machine_id -> list of placed entries

    for job in order:
        eligible = job["EligibleMachineIds"]
        if not eligible:
            return None

        # Earliest start allowed by precedence (all predecessors finished).
        prec_floor = 0
        for pred_id in job["PrecedenceJobIds"]:
            pred = scheduled.get(pred_id)
            if pred is not None:
                prec_floor = max(
                    prec_floor,
                    pred["StartTime"] + input_jobs[pred_id]["ProcessingTime"],
                )

        # Try every eligible machine, keep the earliest feasible placement.
        best_start = None
        best_machine = None
        for machine_id in eligible:
            on_m = jobs_on_machine.get(machine_id)
            if on_m:
                # Jobs on a machine are placed in increasing start order, so the
                # last one placed is the latest / the direct predecessor here.
                last = on_m[-1]
                last_id = last["JobId"]
                last_end = last["StartTime"] + input_jobs[last_id]["ProcessingTime"]
                setup_time = job["JobSetupTimes"][last_id - 1]
                base = max(prec_floor, last_end + setup_time)
            else:
                base = max(prec_floor, job["InitialSetupTime"])

            start = _earliest_feasible_start(
                job, base, solution, input_data, input_jobs
            )
            if start is not None and (best_start is None or start < best_start):
                best_start = start
                best_machine = machine_id

        if best_start is None:
            return None

        entry = {
            "JobId": job["Id"],
            "StartTime": best_start,
            "MachineId": best_machine,
            "ProcessingTime": job["ProcessingTime"],
            "DueTime": job["DueTime"],
        }
        solution.append(entry)
        scheduled[job["Id"]] = entry
        jobs_on_machine.setdefault(best_machine, []).append(entry)

    return solution


def rebuild_schedule(solution, input_data):
    """
    Recalculate start times for a solution.

    The solution list gives us:
    - the jobs
    - their machine assignments
    - their current order in the list

    This function rebuilds StartTime values from scratch while respecting:
    - precedence constraints
    - machine order and setup times
    - initial setup times
    - resource capacities
    """
    input_jobs = {job["Id"]: job for job in input_data["Jobs"]}
    input_job_ids = {job["Id"] for job in input_data["Jobs"]}

    # Reset start times. They should be calculated from scratch.
    for job in solution:
        job["StartTime"] = 0

    scheduled = {}  # job_id -> scheduled job
    rebuilt = []  # final rebuilt schedule
    remaining = copy.deepcopy(solution)

    # Safety bound to prevent infinite searching for a resource-feasible time.
    # This is not mathematically perfect, but good enough for now.
    total_processing_time = sum(job["ProcessingTime"] for job in input_data["Jobs"])
    max_setup_time = max(
        max(job["JobSetupTimes"]) if job["JobSetupTimes"] else 0
        for job in input_data["Jobs"]
    )
    horizon_limit = (
        total_processing_time * len(input_data["Jobs"])
        + max_setup_time * len(input_data["Jobs"])
        + 1000
    )

    while remaining:
        progress = False

        for job in remaining[:]:
            job_id = job["JobId"]
            ctx_job = input_jobs[job_id]
            machine_id = job["MachineId"]

            # Machine eligibility check.
            # If a neighbour assigned the job to an invalid machine, this solution cannot be rebuilt.
            if machine_id not in ctx_job["EligibleMachineIds"]:
                remaining.remove(job)
                return None

            # Only schedule this job once all predecessors have already been scheduled.]
            if not all(
                pred_id in scheduled
                for pred_id in ctx_job["PrecedenceJobIds"]
                if pred_id in input_job_ids
            ):
                continue

            # Earliest start due to precedences.
            start_time = 0
            for pred_id in ctx_job["PrecedenceJobIds"]:
                if pred_id not in input_job_ids:
                    continue
                pred = scheduled[pred_id]
                pred_ctx = input_jobs[pred_id]
                pred_end = pred["StartTime"] + pred_ctx["ProcessingTime"]
                start_time = max(start_time, pred_end)

            # Earliest start due to previous job on the same machine.
            previous_jobs_on_machine = [
                j for j in rebuilt if j["MachineId"] == machine_id
            ]

            if previous_jobs_on_machine:
                last_job = previous_jobs_on_machine[-1]
                last_job_id = last_job["JobId"]
                last_ctx = input_jobs[last_job_id]
                last_end = last_job["StartTime"] + last_ctx["ProcessingTime"]

                # Setup time for current job after last job.
                setup_time = ctx_job["JobSetupTimes"][last_job_id - 1]
                start_time = max(start_time, last_end + setup_time)
            else:
                # First job on this machine.
                start_time = max(start_time, ctx_job["InitialSetupTime"])

            # Resource-aware part:
            # If resources are not available at this start time, delay the job by
            # jumping to the next capacity/job event (stepping +1 is catastrophically
            # slow on large horizons and could effectively hang).
            feasible_start = _earliest_feasible_start(
                ctx_job, start_time, rebuilt, input_data, input_jobs
            )
            if feasible_start is None or feasible_start > horizon_limit:
                return None
            start_time = feasible_start

            new_job = copy.deepcopy(job)
            new_job["StartTime"] = start_time
            new_job["ProcessingTime"] = ctx_job["ProcessingTime"]
            new_job["DueTime"] = ctx_job["DueTime"]

            rebuilt.append(new_job)
            scheduled[job_id] = new_job
            remaining.remove(job)
            progress = True

        if not progress:
            # Usually means precedence deadlock or impossible ordering.
            return None

    return rebuilt


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
