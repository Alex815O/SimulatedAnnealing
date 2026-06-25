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

% -----------------------------
% Machine eligibility
% -----------------------------

constraint forall(j in 1..J)(
  allowedMachines[j, mach[j]]
);

% -----------------------------
% Non-overlap + setup on same machine
% -----------------------------
% If two jobs are on the same machine, one must finish plus setup
% before the other starts.

constraint forall(i, j in 1..J where i < j)(
  mach[i] != mach[j] \/
  endTime[i] + setupTime[j, i] <= start[j] \/
  endTime[j] + setupTime[i, j] <= start[i]
);

% -----------------------------
% Initial setup
% -----------------------------
% Simplified safe version:
% every job starts after its initial setup time.
% This is stronger than necessary, but valid.

constraint forall(j in 1..J)(
  start[j] >= initSetupTime[j]
);

% -----------------------------
% Precedence constraints
% -----------------------------

constraint forall(j, p in 1..J where preJobs[j, p])(
  endTime[p] <= start[j]
);

% -----------------------------
% Resource capacity constraints
% Task decomposition version
% -----------------------------
% Instead of checking every timestamp t = 0..T-1,
% we only check resource usage at each job start time.
%
% This is much smaller than time decomposition:
% old: R * T * J
% new: R * J * J

constraint forall(r in 1..R, i in 1..MAX_CAPACITY_CHANGE-1)(
  sum(j in 1..J)(
    bool2int(
      start[j] < capacityChange[i+1] /\ endTime[j] > capacityChange[i]
    ) * requiredCapacity[j, r]
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

% solve satisfy;
solve
:: int_search(
     [mach[j] | j in 1..J] ++ [start[j] | j in 1..J],
     input_order,
     indomain_min,
     complete
   )
minimize objective;

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
