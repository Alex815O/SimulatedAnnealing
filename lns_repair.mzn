int: M;
int: J;
int: R;
int: T;
int: MAX_CAPACITY_CHANGE;


array[1..J] of int: jobsDuration;
array[1..J] of int: jobsDueTime;
array[1..J, 1..M] of bool: allowedMachines;
array[1..J, 1..R] of int: requiredCapacity;
array[1..J, 1..J] of bool: preJobs;
array[1..J] of int: initSetupTime;
array[1..J, 1..J] of int: setupTime;
array[1..MAX_CAPACITY_CHANGE] of int: capacityChange;
array[1..R, 1..MAX_CAPACITY_CHANGE-1] of int: resourceCapacity;

array[1..J] of bool: is_frozen;
array[1..J] of int: fixed_start;
array[1..J] of int: fixed_machine;

% Time window the free (non-frozen) jobs must be rescheduled into. In an LNS
% repair the free jobs come from a contiguous time window of the current
% solution, and their original positions already fit inside [WINDOW_LB,
% WINDOW_UB]. Restricting them to that window keeps the original schedule
% feasible while shrinking the free start-time domains enormously, which is what
% makes the repair fast. For a full solve these default to 0 / T (no restriction).
int: WINDOW_LB;
int: WINDOW_UB;

% A free job always runs inside [WINDOW_LB, WINDOW_UB]. These par predicates let
% the constraints below skip frozen jobs and capacity intervals that cannot
% interact with any free job, so they never enter the flattened model. That is
% what makes the repair fast: only the window-relevant part of the instance is
% sent to the solver, even though the data still describes the whole instance.
% With the default window (0 .. T) every job/interval qualifies, so a full solve
% is unaffected.

% The job's fixed interval overlaps the window. Only such frozen jobs can run at
% the same time as a free job and therefore compete for a machine or a resource.
function bool: window_active(int: j) =
  not is_frozen[j]
  \/ (fixed_start[j] < WINDOW_UB /\ fixed_start[j] + jobsDuration[j] > WINDOW_LB);

% The job actually STARTS inside the window. Only at such start times can a free
% job be running, so only these start times need a resource-peak check.
function bool: starts_in_window(int: j) =
  not is_frozen[j]
  \/ (WINDOW_LB <= fixed_start[j] /\ fixed_start[j] < WINDOW_UB);

% A capacity interval is window-relevant if it overlaps the window; only then can
% a free job be running during it.
function bool: interval_in_window(int: i) =
  capacityChange[i] < WINDOW_UB /\ capacityChange[i + 1] > WINDOW_LB;

% -----------------------------
% Decision variables
% -----------------------------

array[1..J] of var 0..T-1: start;
array[1..J] of var 1..M: mach;
array[1..J] of var 0..T: endTime =
  [start[j] + jobsDuration[j] | j in 1..J];
  
% -----------------------------
% Frozen jobs for LNS repair
% -----------------------------
% Jobs outside the selected neighborhood keep their old start time and machine.
% Only non-frozen jobs may be changed by MiniZinc.

constraint forall(j in 1..J where is_frozen[j]) (
  start[j] = fixed_start[j] /\
  mach[j] = fixed_machine[j]
);

% Keep the free jobs inside the repair window (see WINDOW_LB / WINDOW_UB above).
constraint forall(j in 1..J where not is_frozen[j]) (
  start[j] >= WINDOW_LB /\
  endTime[j] <= WINDOW_UB
);

% -----------------------------
% Machine eligibility
% -----------------------------

constraint forall(j in 1..J)(
  allowedMachines[j, mach[j]]
);

% -----------------------------
% Non-overlap on the same machine
% -----------------------------
% Two jobs on the same machine may never overlap in time.
% Pairs where BOTH jobs are frozen are skipped: their positions come from the
% current (already valid) solution and cannot change, so they never overlap.
% A frozen job whose interval lies outside the window cannot overlap a free job
% either (the free job runs inside the window), so it is skipped as well.

constraint forall(i, j in 1..J where
  i < j
  /\ not (is_frozen[i] /\ is_frozen[j])
  /\ window_active(i) /\ window_active(j)
)(
  mach[i] != mach[j] \/
  endTime[i] <= start[j] \/
  endTime[j] <= start[i]
);

% -----------------------------
% Sequence-dependent setup time
% -----------------------------
% Setup time is only required between two jobs that run DIRECTLY one after the
% other on the same machine. This matches the validator (check_setup_times),
% which sorts the jobs on each machine by start time and only checks each job
% against its immediate predecessor.
%
% The previous version required setupTime[j, i] between every pair where i runs
% before j, even when other jobs ran in between. With sequence-dependent setup
% times that is too strong: it rejected valid schedules (and made the LNS repair
% infeasible, so MiniZinc never produced a neighbour).
%
% job i is the direct predecessor of job j iff they share a machine, i starts
% before j, and no other job on that machine starts between them.
%
% Pairs where BOTH jobs are frozen are skipped: their relative setup was already
% satisfied in the current (valid) solution and cannot change. If a free job is
% moved between two frozen jobs, the (frozen, free) and (free, frozen) pairs are
% still generated, so the setup around it is enforced.

constraint forall(i, j in 1..J where i != j /\ not (is_frozen[i] /\ is_frozen[j]))(
  (
    mach[i] == mach[j]
    /\ start[i] < start[j]
    /\ not exists(k in 1..J where k != i /\ k != j)(
         mach[k] == mach[i] /\ start[i] < start[k] /\ start[k] < start[j]
       )
  )
  -> endTime[i] + setupTime[j, i] <= start[j]
);

% -----------------------------
% Initial setup
% -----------------------------
% The validator only requires the FIRST job on each machine to respect its
% InitialSetupTime. Every other job is covered by the inter-job setup time in
% the non-overlap constraint above. So a job needs its initial setup time only
% if no other job on the same machine starts before it.

constraint forall(j in 1..J)(
  start[j] >= initSetupTime[j]
  \/ exists(k in 1..J where k != j)(
       mach[k] = mach[j] /\ start[k] < start[j]
     )
);

% -----------------------------
% Precedence constraints
% -----------------------------

constraint forall(j, p in 1..J where preJobs[j, p])(
  endTime[p] <= start[j]
);

% -----------------------------
% Resource capacity constraints
% Concurrent (cumulative) version
% -----------------------------
% A resource is only overloaded when jobs that run AT THE SAME TIME need more
% capacity than is available. The previous version summed every job that
% overlapped a whole capacity interval, which also counted jobs that merely run
% one after another inside that interval. That rejected perfectly valid, densely
% packed schedules and made MiniZinc infeasible on realistic instances (so the
% LNS repair always fell back to greedy and never found a MiniZinc neighbour).
%
% Resource usage can only peak at a job start time or at a capacity-change time,
% so it is enough to check those points. At each such time t, the jobs running
% at t (start[k] <= t < endTime[k]) must fit into the capacity available at t.

% Peak usage at every job start time, against the capacity of the interval that
% contains that start time.
% Only start times INSIDE the window need checking: at a start time outside it,
% no free job is running, so the (frozen-only) load is the current solution's and
% already valid. The inner sum keeps every job whose interval overlaps the window
% (a frozen job spanning into the window still consumes capacity there).
constraint forall(r in 1..R, j in 1..J where starts_in_window(j))(
  sum(k in 1..J where window_active(k))(
    bool2int(start[k] <= start[j] /\ start[j] < endTime[k]) * requiredCapacity[k, r]
  )
  <=
  sum(i in 1..MAX_CAPACITY_CHANGE-1 where interval_in_window(i))(
    bool2int(capacityChange[i] <= start[j] /\ start[j] < capacityChange[i+1])
      * resourceCapacity[r, i]
  )
);

% Peak usage at every capacity-change time. This catches jobs that span a
% boundary into a lower-capacity interval (their start time alone would be
% checked against the higher, earlier capacity).
% Only capacity changes inside the window can affect a free job; outside it the
% load is frozen-only and already valid.
constraint forall(r in 1..R, i in 1..MAX_CAPACITY_CHANGE-1
    where interval_in_window(i) /\ capacityChange[i] >= WINDOW_LB)(
  sum(k in 1..J where window_active(k))(
    bool2int(start[k] <= capacityChange[i] /\ capacityChange[i] < endTime[k])
      * requiredCapacity[k, r]
  ) <= resourceCapacity[r, i]
);

% -----------------------------
% Objective
% -----------------------------

var int: makespan = max(j in 1..J)(endTime[j]);

var int: total_tardiness =
  sum(j in 1..J)(
    max(0, endTime[j] - jobsDueTime[j])
  );

var int: objective = total_tardiness + makespan;

% -----------------------------
% Search strategy
% -----------------------------

solve satisfy;
% solve
% :: int_search(
%      [mach[j] | j in 1..J] ++ [start[j] | j in 1..J],
%      input_order,
%      indomain_min,
%      complete
%    )
% minimize objective;

% -----------------------------
% Output as required solution JSON
% -----------------------------

output [
  "{\n",
  "  \"Jobs\": [\n",
  concat([
    "    {\"JobId\": " ++ show(j) ++
    ", \"StartTime\": " ++ show(start[j]) ++
    ", \"MachineId\": " ++ show(mach[j]) ++
    "}" ++
    if j < J then ",\n" else "\n" endif
    | j in 1..J
  ]),
  "  ]\n",
  "}\n"
];
