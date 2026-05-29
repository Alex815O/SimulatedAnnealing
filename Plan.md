# Assignment 2 - Workitems

- [ ] Problem-Encoding, design how a solution is representet
- [ ] Greedy Solution generator for starting point
- [ ] evaluation function (this contains all requirements for the solution), and return a the score
- [ ] Neighbourhood generation
  - [x] How are invalid neighbours handeld? [Neighbourhood](Plan.md#Neighbourhood)
- [ ] Simulated Anealing Alogithmn
- [ ] Visualisation with MatPlotLib / Logging / Metrics
- [ ] Run on all .json files skript
- [ ] Parameter Tuning (use Optima)
- [X] Solution Validation
  - Solved via the validator

# Design Descision

## Problem Encoding

Input.json file will be stored as Python Dict, thats the easyiest approach
The output will be a dict/json:
We also Add meta data, to the solution/neigbourhood dict, otherwise, we would need to do many slow joins
```json
{
  "Jobs": [
    { "JobId": 1, "StartTime": 2536, "MachineId": 1, "EndTime": 0, "DueTime": 0 },
    { "JobId": 2, "StartTime": 3391, "MachineId": 1, "EndTime": 0, "DueTime": 0 },
    { "JobId": 3, "StartTime": 3131, "MachineId": 1, "EndTime": 0, "DueTime": 0 },
    { "JobId": 4, "StartTime": 29, "MachineId": 1, "EndTime": 0, "DueTime": 0 },
    { "JobId": 5, "StartTime": 3486, "MachineId": 1, "EndTime": 0, "DueTime": 0 },
    { "JobId": 6, "StartTime": 136, "MachineId": 1, "EndTime": 0, "DueTime": 0 },
      { "JobId": 7, "StartTime": 2058, "MachineId": 1, "EndTime": 0, "DueTime": 0 },
      { "JobId": 8, "StartTime": 2629, "MachineId": 1, "EndTime": 0, "DueTime": 0 },
      { "JobId": 9, "StartTime": 1428, "MachineId": 2, "EndTime": 0, "DueTime": 0 },
      { "JobId": 10, "StartTime": 742, "MachineId": 1, "EndTime": 0, "DueTime": 0 }
  ]
}
```


## Neighbourhood

Let's try diffrent appraoches
Mystral AI reasarch:

```
🔹 Strategie 1: Verhindern (Constraint-Aware Generation)
Idee: Nur gültige Nachbarn generieren – invalid Solutions werden nie erzeugt.
Wie?
• Die Nachbarschaftsfunktion kennt alle Constraints und wendet nur gültige Änderungen an.
• Beispiel Job Scheduling:
▪ 
Wenn du einen Job auf eine andere Maschine verschiebst, prüfst du vorher, ob die Maschine den Job bearbeiten darf.
▪ 
Wenn du Jobs auf einer Maschine tauscht, simulierst du die neuen Startzeiten und prüfst, ob es Überschneidungen gibt.
Vorteile: ✅ Keine invalid Solutions → Evaluation muss nicht prüfen. ✅ SA erkundet nur den gültigen Suchraum → Effizienter. ✅ Keine Strafterme nötig → Evaluation-Funktion bleibt einfach.
Nachteile: ❌ Komplexere Nachbarschaftsfunktion (muss alle Constraints kennen). ❌ Kleinere Nachbarschaft → SA könnte lokaler stecken bleiben (weil weniger Nachbarn verfügbar sind). ❌ Schwierig bei komplexen Constraints (z. B. "Job A muss vor Job B, aber nach Job C").
🔹 Strategie 2: Bestrafen (Penalty Function)
Idee: Invalid Solutions zulassen, aber sie in der Evaluation-Funktion bestrafen.
Wie?
• Die Evaluation-Funktion berechnet:
▪ Normalen Score (z. B. Makespan).
▪ + Strafterm für jedes versteckte Constraint.
• Beispiel Job Scheduling:
▪ Wenn zwei Jobs auf Maschine 1 überschneiden: Score = Makespan + 1000 (hohe Strafe).
▪ Wenn ein Job auf einer unerlaubten Maschine läuft: Score = Makespan + 10000 (noch höhere Strafe).
Vorteile: ✅ Einfache Nachbarschaftsfunktion (muss keine Constraints prüfen). ✅ SA kann ungültige Lösungen akzeptieren → Kann aus ungültigen Bereichen herausfinden. ✅ Flexibel – funktioniert auch mit komplexen Constraints.
Nachteile: ❌ Strafe muss gut kalibriert sein:
• Zu niedrig → SA akzeptiert zu viele invalid Solutions.
• Zu hoch → SA vermeidet alle invalid Solutions (wie Strategie 1, aber ineffizienter). ❌ Evaluation wird langsamer (muss alle Constraints prüfen).
Wichtig:
• Die Strafe sollte skalierbar sein (z. B. proportional zur Schwere der Verletzung).
• Makespan = 1000, Strafe = 1e9 → SA wird invalid Solutions nie akzeptieren.
• Makespan = 1000, Strafe = 100 → SA könnte invalid Solutions akzeptieren, wenn der restliche Score besser ist.
🔹 Strategie 3: Reparieren (Repair Mechanism)
Idee: Wenn ein invalid Solution generiert wird, automatisch reparieren (z. B. durch Anpassung der Lösung).
Wie?
 1. Generiere einen Nachbarn ohne Constraint-Prüfung (z. B. zufälliger Swap).
 2. Prüfe, ob der Nachbar gültig ist.
 3. Falls nein: Repariere ihn (z. B. durch:
• Verschieben eines Jobs auf eine andere Maschine.
• Anpassen der Startzeiten, um Überschneidungen zu vermeiden.
• Entfernen von Jobs, die Constraints verletzen.
 4. Gib die reparierte Lösung zurück.
Vorteile: ✅ Nachbarschaftsfunktion bleibt einfach (generiert zuerst beliebige Nachbarn). ✅ SA bleibt im gültigen Suchraum (nach der Reparatur). ✅ Keine Strafterme nötig → Evaluation bleibt einfach.
Nachteile: ❌ Reparatur kann aufwendig sein (z. B. NP-schwer bei komplexen Constraints). ❌ Reparatur könnte die Lösung stark verändern → Der Nachbar ist nicht mehr eine kleine Änderung der ursprünglichen Lösung. ❌ Schwierig zu garantieren, dass die Reparatur immer funktioniert.
```
