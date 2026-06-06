def preprocessing(context):
    R = len(context["Resources"])
    T = resource_horizon(context["Resources"], context["Jobs"])
    (capacity_changes, resource_capacity) = calculate_resource_change_events(
        context["Resources"], R, T
    )
    context["ResourceEvents"] = {
        "capacity_changes": capacity_changes,
        "resource_capacity": resource_capacity,
    }
    return context


def calculate_resource_change_events(resources, R, T):
    capacity_changes = []

    if R > 0:
        capacity_changes = sorted(
            {
                time
                for resource in resources
                for period in resource["AvailabilityPeriods"]
                for time in (period["Start"], period["End"])
            }.union({T})
        )

    resource_capacity = [
        [
            next(
                (
                    period["Capacity"]
                    for period in resource["AvailabilityPeriods"]
                    if period["Start"] <= time < period["End"]
                ),
                0,
            )
            for time in capacity_changes[:-1]
        ]
        for resource in resources
    ]

    return capacity_changes, resource_capacity


def resource_horizon(resources, jobs):
    # Last timestamp from resource availability
    last_resource_time = max(
        [resource["AvailabilityPeriods"][-1]["End"] for resource in resources],
        default=0,
    )

    # Safe scheduling horizon:
    # all jobs one after another, including initial setup and worst-case setup between jobs.
    total_processing_time = sum(job["ProcessingTime"] for job in jobs)

    max_initial_setup = max([job["InitialSetupTime"] for job in jobs], default=0)

    max_setup_time = max(
        [setup for job in jobs for setup in job["JobSetupTimes"]], default=0
    )

    safe_schedule_horizon = max_initial_setup + total_processing_time

    T = max(last_resource_time, safe_schedule_horizon)
    return T
