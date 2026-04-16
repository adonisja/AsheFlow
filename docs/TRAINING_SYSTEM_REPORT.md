# AsheFlow: Training & Trainee System Features Report

This report outlines the dedicated features implemented to handle the lifecycle of Trainees and the tools provided to Trainers, Dispatchers, and Management.

## 1. System Overview

We established a comprehensive, day-by-day training module that directly hooks into the algorithmic dispatch engine. The system automates what tasks a trainee needs to accomplish on any given shift based on their historical progression, while granting oversight to the different roles interacting with the training lifecycle.

## 2. The Trainer Dashboard (Trainer View)

**Access Level:** Strictly limited to users with the `trainer` role.
**Route:** `/trainer-dashboard`

The Trainer Dashboard is a dynamic, context-aware environment built to assist active trainers on the floor. 

**Key Features:**
*   **Automatic Trainee Resolution:** The system queries today's schedule, determines which truck the logged-in trainer is assigned to, and retrieves the specific trainee paired with them for that exact shift.
*   **Lifecycle Awareness:** Displays what "Day" of the training program the trainee is on, providing context to the trainer.
*   **Daily Task Checklist:** Rendered interactively. Trainers can check off specific goals and topics (e.g., CPR operations, lifting mechanics). Checked tasks automatically sync via an API backend.
*   **Training Debt Tracking:** Overdue/missed tasks from previous days are automatically appended to today's dashboard wrapped in a high-priority "Training Debt" alert.
*   **Historical Log View:** The trainer can view the aggregate history of their assigned trainee, helping them understand what concepts the trainee has previously struggled with or mastered.
*   **Management Directives:** A dedicated read-only section where trainers can read specific daily comments pushed down from management.

## 3. The Trainee Hub (Management View)

**Access Level:** Strictly limited to the `management` and `admin` roles.
**Route:** `/trainee-management`

The Trainee Hub serves as the administrative oversight panel for monitoring the entire training program.

**Key Features:**
*   **Global Trainee Lookup:** Managers can select any active trainee in the system from a global dropdown menu.
*   **Comprehensive Progress Logs:** Retrieves a full day-by-day summary of the selected trainee's lifecycle. Managers can view exactly which tasks were marked complete, which tasks were failed, and who the trainee was locked with on those shifts.
*   **Live Shift Inspection:** Displays a read-only version of the Task Checklist that the trainer is currently looking at for the current day.
*   **Manager Notes Injection:** Provides a direct mechanism for managers to write and append directives directly to the trainee's active record. These notes are immediately visible to the active trainer on their dashboard.

## 4. The Dispatch Center (Dispatch View)

**Access Level:** Users with `dispatch`, `management`, or `admin` roles.
**Route:** `/dispatch`

While dispatchers do not have access to the deep analytics of the Trainee Hub, they maintain necessary operational control over the vehicles.

**Key Features:**
*   **Algorithmic Injection:** When dispatch is run, the engine automatically checks if a truck contains a trainee. If so, it invokes the curriculum service to generate a target training record for that shift.
*   **Manual Overrides:** Dispatchers can manually drag and drop trainers or trainees between trucks. The system ensures that the proper state is preserved and prevents destructive overlaps.

## 5. Security & Role Breakdown Matrix

The application's core router strictly guards paths based on the AWS Cognito claims (`groups`).

| Feature / Route | Trainers | Dispatchers | Management / Admins | Trainees (Direct) |
| :--- | :---: | :---: | :---: | :---: |
| **Worker Dashboard (`/`)** | Yes | Yes | Yes | Yes |
| **Schedule / Preferences** | Yes | Yes | Yes | Yes |
| **Trainer Dashboard (`/trainer-dashboard`)** | **Yes** | No | No | No |
| **Dispatch Center (`/dispatch`)**| No | **Yes** | **Yes** | No |
| **Trainee Hub (`/trainee-management`)**| No | No | **Yes** | No |
| **Asset Manager (`/assets`)** | No | No | **Yes** | No |

*Note: In Edge cases where a user possesses multiple roles (e.g., an Admin who is also a Trainer), they will see all combined features.*

## 6. Backend Integration

The backend powers these frontend features through:
*   `training_injection.py`: Curriculum resolution logic that analyzes a trainee's `current_day_number` and handles bumping missed items into "debt".
*   `run_dispatch.py`: Hooks the training logic into the algorithmic sorting matrix.
*   `training_routes.py`: A dedicated set of REST endpoints for fetching active targets, writing management notes, and patching boolean completion statuses.