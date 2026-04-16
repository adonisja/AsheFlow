# Trainer Dashboard & Trainee Tracking Plan

## Overview
This document outlines the requirements and tasks needed to build out the **Trainer Dashboard** within AsheFlow. The goal is to provide Trainers and Management with a comprehensive, stateful tracking system for Trainees as they progress through their 5-day onboarding cycle before graduating to Walkers.

## Core Features & Requirements

### 1. Real-Time Pairing Visibility
- **Dynamic Updates:** When a trainee is assigned to a trainer by the dispatch algorithm (or via manual override), the trainer's dashboard must clearly display the pairing.
- **Contextual UI:** The dashboard should highlight who the assigned trainee is for the current day.

### 2. Historical Context & Record
- **Past Training Logs:** The trainee's record must include historical context detailing what they have been trained on during previous days.
- **Continuity:** These records are filled in by previous trainers to ensure a seamless handoff if the trainee is paired with a different trainer on subsequent days.
- **New Hires:** If the trainee is completely new (Day 1), this historical section will be empty but properly formatted to receive its first entry.

### 3. Day-by-Day Training Tasks (The Guide)
- **Structured Curriculum:** A predefined, day-specific curriculum must be presented to the trainer.
  - *Example - Day 1 Outline:* Login and sign-in procedures, work hours, dress code, basic safety.
- **Checklist Form:** Trainers should be able to check off topics as they are covered throughout the day.

### 4. Assignment Day Tracking
- **Lifecycle Counter:** The system needs to calculate and prominently display the trainee's current training day out of their 5-day lifecycle (e.g., `"Trainee Tyler - Day 3"`).

### 5. Training Debt
- **Rollover Mechanics:** Any training topics or tasks that were missed on a previous day must automatically roll over and be clearly flagged as "Training Debt" on the current day's dashboard.
- **Priority Visibility:** Debt items should be prioritized so the current trainer knows exactly what critical information was skipped previously.

### 6. Individualized Comments Section
- **Trainer Feedback:** A dedicated text area for the active trainer to leave qualitative, individualized comments and feedback regarding the trainee's performance, attitude, and learning curve for that specific day.

### 7. Visibility and Immutability (Record Locking)
- **Role-Based Visibility:** 
  - **Trainers** only get to view their *own* daily and historical records (i.e., records for trainees they personally trained).
  - **Managers** must be able to see *all* daily and historical pairings across all trainers and trainees.
- **Active Editing:** The trainer currently assigned to the trainee possesses write-access to the record **only during that specific assigned day**.
- **End-of-Day Locking:** Once the day has officially ended (or upon explicit confirmation/submission by the trainer), the record permanently locks. It becomes an immutable historical log that cannot be altered retroactively.

### 8. Managerial Oversight & Manual Interventions
- **Manager Comments:** Managers can leave comments for topics or tasks to go over with a trainee for the current or future assignment.
- **Manual Assignment & Overrides:** Managers can manually assign a trainee to a trainer for the next or current day.
  - *Current Day Rules:* If manually assigned to a trainer for the current day, that trainee is automatically assigned to the truck the trainer is on. 
  - If the trainer already has a trainee, the old trainee gets reassigned to another available trainer. 
  - If the trainer doesn't have one, this newly assigned trainee is mapped directly to them and skipped during the automatic algorithm's first pass for daily assignments.

---

## Implementation Tasks (TODOs)

### Backend (FastAPI / PostgreSQL)
- [ ] **Schema & Models:** Create new SQLAlchemy models for `TrainingRecord`, `TrainingTask`, and `TrainingCurriculum` to support the day-by-day mapping and historical tracking.
- [ ] **Endpoints:** Create API routes to fetch a trainee's full history (`GET /api/v1/training/trainee/{id}`). Enforce RBAC filtering (Managers see all, Trainers see their own).
- [ ] **Managerial Comments:** Add endpoints to append Manager-specific tasks/comments (`POST /api/v1/training/trainee/{id}/manager-comments`).
- [ ] **Curriculum Injection:** Build logic to determine the trainee's current "Day X" and auto-generate the pending tasks and roll over any "Training Debt" from the previous record.
- [ ] **Immutability Logic:** Enforce a check on `PUT/PATCH` requests to ensure the current timestamp is within the active assignment day bounds; reject edits if the record is locked/expired.
- [ ] **Manual Trainee Override Logic:** Update manual dispatch route (`POST /api/v1/dispatch/assign-trainee-to-trainer`) to identify the trainer's truck, move the trainee there, bump existing trainees to available fallback trainers, and adjust the automatic dispatch algorithm's "first pass" so it respects these locked/pre-assigned trainees.

### Frontend (React / Tailwind)
- [ ] **Trainer Dashboard Route:** Create a new dedicated view or expanded widget within the Worker Portal specifically for users with the `trainer` role (filtered to their own history).
- [ ] **Management Overview Route:** Build an aggregate view in the Management Portal to let managers monitor all current and past pairings, with forms to leave specific notes/tasks for trainees.
- [ ] **Manager Override UI:** Add a "Assign to Trainer" modal in the Manager Dashboard allowing them to link a specific trainee directly to a specific trainer for a given day.
- [ ] **Pairing Display Component:** Build a component that fetches today's dispatch data and highlights the trainer's assigned trainee.
- [ ] **Trainee Profile Modal/Page:** Develop the UI to display the "Trainee Tyler - Day 3" header, historical records timeline, and the day's specific task checklist.
- [ ] **Form & Comments:** Build the editable form for checking off tasks and entering comments. Display Manager comments distinctly.
- [ ] **Lock State UI:** Implement conditional rendering to convert inputs into disabled, read-only text blocks if `isLocked` is true or if the active user is not the assigned trainer for that day.