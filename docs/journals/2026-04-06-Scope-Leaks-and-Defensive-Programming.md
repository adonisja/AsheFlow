# Engineering Journal: April 6, 2026

**Session Start Time**: April 6, 2026, 09:00 AM
**Session End Time**: [In Progress]

## Goal for the Session
Address code review feedback regarding scope leaks and uninitialized variables in `calculate_weights.py` during the mutual bonus (bidirectional/tridirectional) assignment phase.

## Problems Encountered
1. **Uninitialized Variables (`NameError`)**: In the `calculate_weights` loop over `fans_by_role`, if a role had zero matches, execution skipped straight to `if boosted_truck_id:` before the variable was ever defined, crashing the application.
2. **Variable Leakage (`fan_id`)**: Python loops "leak" their iteration variables. The code was attempting to check `perform_bidirectional_check` using a `fan_id` that was assigned in a previous, completely unrelated `for` loop. This caused the algorithm to calculate bonuses against entirely random users instead of the fan actually placed on the winning truck.
3. **Generator Fragility (`StopIteration`)**: When calling `next(generator)`, if the generator is empty, Python throws a hard runtime error. While system invariants upstream guaranteed drivers and trainers would exist before walkers were calculated, the algorithm was structurally brittle and vulnerable to crashes if that external flow ever changed.

## Solutions & Procedures
1. **Explicit Loop Initialization**: Hardcoded `boosted_truck_id = None` at the very start of the `for role in fans_by_role:` loop. This creates a clean slate for every iteration and prevents old data from bleeding over while satisfying the truthy check below.
2. **Correct Context Extraction**: Removed the leaked loop variable. Re-extracted the correct `fan_id` explicitly for the winning truck using `fan_id = fans_by_truck[boosted_truck_id][0]`.
3. **Defensive Programming (`next` defaults)**: Injected `None` as a fallback object in the `next()` generator calls (e.g., `next((...), None)`) and guarded the tridirectional math check with an `if driver_id and trainer_id:` assertion.

## Key Takeaways
* **Beware Python Loop Scope Leaks**: Unlike block-scoped languages (like JavaScript with `let`, `const`), Python variables declared inside a `for` loop persist after the loop finishes. Never rely on an iteration variable surviving outside its scope to represent specific business logic; explicitly extract what you need.
* **System Invariants vs. Defensive Programming (Defense in Depth)**: Even when business logic guarantees a specific state (i.e. Drivers *must* be assigned before Walkers), it is a Senior Engineering practice to defensively code against those guarantees breaking. Safe defaults prepare the function for future refactors, concurrent execution, and easier, isolated Unit Testing that doesn't require fully mocking the entire upstream pipeline state.
