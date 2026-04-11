# ADR-007: Trainer Dashboard Frontend Architecture

## Status
Proposed -> Accepted

## Context
We need a robust tracking system for trainers to log their trainee's 5-day cycle. Key features include role-based data rendering (Trainers see their own, Managers see all) and immutability rules based on the assignment date.

## Decision
- We will organize the Trainer Dashboard into an isolated React page `TrainerDashboard/index.tsx` within the `frontend/src/pages/` structure.
- We will decouple the "Checklist" (TrainingTasks log) and "Comments" into modular subcomponents inside `frontend/src/components/TrainerDashboard/`.
- For state management and data fetching, we are relying on explicit API calls via our established standard Axios utility functions, rather than heavyweight state providers, given the relative simplicity of a single-day lifecycle view per trainer.

## Consequences
- Requires strict validation logic down correctly into the child properties for boolean 'locked/disabled' states based on the database `is_locked` value.
- Clear separation of concerns that makes it easier to extend with "Manager View" abstractions heavily reusing the same underlying presentation components but feeding them a full dataset.