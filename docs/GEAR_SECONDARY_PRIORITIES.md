# Gear Optimizer secondary priorities

The shared optimizer accepts `secondary_priority`, defaulting to `default` (the existing inventory/cost/action/identity ordering). The configuration dropdown also offers Balanced defence, individual Stab/Slash/Crush/Ranged/Magic defence, Prayer bonus, Melee strength bonus, Ranged strength bonus, Magic damage bonus and Accuracy. All options remain available for one to four roles.

Weighted ordinary-attack DPS remains the primary objective. A priority is maximized only when modeled DPS compares exactly equal under the existing float ordering; there is no tolerance or rounded-DPS comparison. Remaining ties use the existing ordering. Candidate retention and partial beams use the selected priority after their DPS estimate, while preserving the existing Fast/Thorough work limits and complete legality checks. Bounded search does not guarantee the best secondary value, or a global DPS optimum.

Metrics come from Python equipment bonuses and combat evaluation. Balanced defence is the arithmetic mean of the five equipment defence bonuses, not a survival estimate. Individual defence, prayer, melee/ranged strength and magic damage use their corresponding equipment bonuses; magic damage is measured in percentage points. Accuracy is the evaluator's hit probability against each role's configured target. Across scored roles, metrics use the same normalized active-time weights as primary DPS; unscored utility roles contribute nothing. Results show the selected priority and measured value separately from DPS (`null` for Default, which has no single numeric metric).

The normalized scenario, its fingerprint, result provenance and every solution carry the selected priority. Switching it makes accepted results outdated and prevents incompatible result/trial comparisons. Omitted and explicit Default requests normalize identically. No combat formulas, catalog rules, search budgets or deployment settings change.

Focused regression entry points are `tests/gear/test_secondary_priorities.py`, `tests/api/test_gear_secondary_priorities.py` and `frontend/gear/src/tests/secondary-priorities.test.tsx`.
