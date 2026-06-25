For Assignment 3:
We integrate Assigment 1 and 2

From the Assignment 3: “combine the exact methods as in assignment 1 with heuristics”
“we recommend Large Neighborhood Search”
“utilize the exact method to solve sub-problems”

Approach: 
Use heuristic / SA / LNS to decide which part of the schedule to change.

Then use MiniZinc / exact method to optimally reschedule only that smaller part.

Then put that improved part back into the full schedule.

We already did soemthing similar in previous assignment with the frozen window stuff
What we did:
freeze most jobs
select a window of jobs
reschedule only that window

but we used a greedy repair here: selected window → greedy_frozen_jobs.py → new neighbour
Now: selected window → MiniZinc exact model → new neighbour

So idea is something like this:

1. Start with a complete feasible schedule.
   For example: greedy solution or your best SA solution.

2. Pick a subset of jobs to reschedule.
   Example:
   - jobs in one time window
   - most tardy jobs
   - jobs on the machine with largest makespan
   - random block of jobs

3. Freeze all other jobs.

4. Build a MiniZinc subproblem:
   - fixed jobs keep their machine and start time
   - selected jobs become decision variables again

5. Run MiniZinc for a short time.
   Example: 1–10 seconds.

6. Insert the MiniZinc result back into the full schedule.

7. If the new full schedule is better, keep it.
   If worse, maybe accept with SA probability or reject.

8. Repeat.


So basically:
neighbourhood_frozen_jobs.py
    chooses which jobs are frozen / flexible

minizinc_repair.py
    actually sends this frozen/flexible subproblem to MiniZinc
    gets back a repaired schedule


minizinc_repair.py is the bridge between Python and MiniZinc.
Python schedule
→ convert to MiniZinc data
→ call MiniZinc
→ read MiniZinc result
→ convert result back to Python schedule
→ validate schedule
