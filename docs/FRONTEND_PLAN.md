# AsheFlow Frontend Architecture & Plan
_Last updated: April 8, 2026_

## 1. Technology Stack
* **Framework:** React 18+ via Vite (TypeScript enabled)
* **Styling:** Tailwind CSS (utility-first, responsive)
* **Authentication/Identity:** AWS Amplify (`@aws-amplify/auth`) to handle Cognito flows
* **State & Data Fetching:** React Query (`@tanstack/react-query`) + Axios
* **Routing:** React Router v6

---

## 2. Authentication Flow & Custom Login UI
**Goal:** Provide a seamless, custom-branded login experience for AsheFlow workers without relying completely on the default AWS Hosted UI.

**Federated Logins Requirements:**
- The login screen must be fully custom designed in React.
- **SSO Options:** Must include "Sign in with Discord" and "Sign in with Google" buttons that wrap the Cognito OAuth flows directly.
- **Traditional Login:** Must include standard Email and Password inputs for direct Cognito User Pool authentication.
- **Token Management:** Upon successful login (either Federated SSO or direct auth), AWS Amplify takes control of the securely stored tokens. 
- **API Interceptor:** Axios is configured to automatically attach the `Bearer {IdToken}` to every outgoing request to our FastAPI backend (`/api/v1/`).

*(Reference `ADR-005-Federated-Identity-Cognito-Discord.md` for AWS SSO configurations)*

---

## 3. Core Dashboards (Separated by RBAC Roles)

### The Dispatcher & Management Dashboard
*Only visible to users with `dispatch`, `management`, or `admin` Cognito groups.*
1. **Daily Dispatch Control:**
   - Date picker to select the dispatch day.
   - A single prominent "Run Dispatch" action button.
   - A realtime feedback log showing the algorithm's decisions, API warnings, or hard failures (e.g., driver shortages).
2. **Review & Manual Override (Post-Dispatch):**
   - A visual grid displaying all finalized truck assignments.
   - Interactive UI (drag-and-drop or select dropdowns) to trigger the `POST`, `PATCH`, or `DELETE /api/v1/dispatch/` override endpoints for sick-calls or shortages.
3. **Asset Management Grid:**
   - Tables with inline editing or modals to manage Employee flags (Activate/Deactivate), Role changes, and Truck states (`is_active`).

### The Worker Portal (Drivers, Trainers, Walkers)
*Visible to everyone, but standard workers are confined to this view.*
1. **My Schedule:**
   - A calendar or list view showing **only** the user's assigned trucks and crew members for the upcoming days.
2. **Preferences Hub:**
   - UI to submit their "Favorites" list (respecting the ADR-001 role-based limits) and their "Ban" list.
   - Form to request or declare upcoming "Off Days" to populate the `EmployeeOffDay` table.

---

## 4. MVP Development Phases
- [x] **Phase 1 (Infra):** Initialize Vite, configure Tailwind, setup `axios` API instance pointing to `http://localhost:8000/api/v1`.
- [x] **Phase 2 (Auth):** Install AWS Amplify, build the custom Login page with Discord/Google Federation buttons.
- [x] **Phase 3 (Core UI):** Scaffold React Router, build the Navigation Bar mapping directly to the JWT `cognito:groups` claims.
- [ ] **Phase 3.5 (Trainer Dashboard):** Implement the dedicated Trainer Dashboard mapping the 5-day stateful trainee curriculum as detailed in `TRAINER_DASHBOARD_PLAN.md`.
- [ ] **Phase 4 (Worker Endpoints):** Hook up the Profile, Preferences (Favorites/Bans), and Off Day submission forms. <-- **_(STARTING NEXT)_**
- [ ] **Phase 5 (Dispatch Engine):** Build the complex interactive Dispatch Grid and the Manual Override tools.