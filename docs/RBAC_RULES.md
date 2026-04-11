# AsheFlow - Business Rules & Access Control

## 🔐 Role-Based Access Control (RBAC) Detailed Specification

### Payroll & Timesheet Business Rules

#### Rule 1: Driver Payroll Visibility
**Decision**: Drivers CANNOT see real-time payroll calculations.

**Rationale**:
- Prevents mid-period disputes
- Avoids hourly rate calculations causing distraction
- Maintains focus on job performance
- Reduces support burden from pay estimate questions

**Implementation**:
```python
# Drivers can see:
- Hours worked (daily/weekly totals)
- Clock in/out timestamps
- Break durations
- "Pending approval" status

# Drivers CANNOT see until payroll closes:
- Hourly rate
- Total earnings
- Deductions
- Tax withholdings
- Net pay
```

#### Rule 2: Timesheet Approval Workflow
**Decision**: Management must approve all timesheets before submission to ADP payroll.

**Workflow**:
```
1. Driver clocks in/out → Creates time entries
2. End of pay period → Time entries locked for editing
3. System generates timesheet → Status: "Pending Approval"
4. Management reviews → Can approve or request corrections
5. Management approves → Status: "Approved"
6. System syncs to ADP → Payroll processing begins
7. ADP processes → Pay calculations finalized
8. Driver can now view → Final pay stub visible in AsheFlow
```

**Authorization Matrix**:
```
Time Entry Actions:
- CREATE: Driver (own entries only)
- READ: Driver (own), Dispatch (team), Management (all)
- UPDATE: Driver (before period close), Management (corrections)
- DELETE: Management only (with audit log)
- APPROVE: Management only

Payroll Actions:
- READ: Management (all), Driver (own, after approval)
- CALCULATE: System only (automated)
- EXPORT: Management only
- SYNC_TO_ADP: System only (after approval)
```

## 👥 Complete Role Permissions Matrix

### Management
**Purpose**: Business oversight, strategic decisions, financial control

**Permissions**:
```yaml
employees:
  - read: all employees, all details
  - create: new employees
  - update: all fields including role, status, pay rate
  - delete: deactivate employees
  - approve: time-off requests, schedule changes

packages:
  - read: all packages, historical data, analytics
  - export: reports and data exports
  - reassign: emergency route changes

routes:
  - read: all routes, performance metrics
  - create: new route templates
  - update: route configurations
  - assign: approve route assignments
  - optimize: run optimization algorithms

timesheets:
  - read: all timesheets
  - approve: required for payroll submission
  - correct: make adjustments with reason
  - export: for reporting/auditing

payroll:
  - read: all payroll data, reports
  - export: financial reports
  - configure: pay rates, deductions, bonuses
  - override: special payments (with audit)

reports:
  - read: all system reports
  - create: custom reports
  - export: all formats (PDF, Excel, CSV)
  - schedule: automated report delivery

settings:
  - read: system configuration
  - update: company settings, integrations
```

### Dispatch
**Purpose**: Daily operations, route coordination, real-time logistics

**Permissions**:
```yaml
employees:
  - read: drivers/walkers only (basic info, status, location)
  - update: shift assignments, availability status

packages:
  - read: all active packages
  - update: status, notes, reassignment
  - scan: mark packages as loaded/delivered
  - photos: view proof of delivery

routes:
  - read: all routes (current and planned)
  - create: daily route assignments
  - update: real-time route modifications
  - assign: assign drivers to routes
  - monitor: track progress in real-time

vehicles:
  - read: all vehicles, maintenance status
  - assign: assign vehicles to drivers
  - update: fuel levels, mileage, issues

timesheets:
  - read: team timesheets (view only)
  - note: cannot approve, can flag issues

communication:
  - send: messages to drivers
  - broadcast: announcements to team
  - alert: emergency notifications

reports:
  - read: operational reports (delivery metrics, driver performance)
  - create: shift reports, daily summaries
```

### Driver
**Purpose**: Execute deliveries, track time, update package status

**Permissions**:
```yaml
profile:
  - read: own profile, documents, certifications
  - update: contact info, emergency contacts (not pay rate)

timesheets:
  - read: own time entries (hours only, not pay)
  - create: clock in/out
  - update: own entries (before period closes)
  - view: "hours worked today/this week"

packages:
  - read: assigned packages only
  - update: delivery status (picked up, delivered, exception)
  - scan: barcode scanning
  - photo: proof of delivery upload
  - note: delivery notes, customer feedback

routes:
  - read: own assigned route only
  - navigate: turn-by-turn directions
  - update: current location, progress

vehicle:
  - read: assigned vehicle info
  - update: pre-trip inspection, issues, mileage

communication:
  - receive: messages from dispatch/management
  - send: messages to dispatch (issues, questions)
  - emergency: SOS/emergency contact

payroll:
  - read: ONLY after pay period closes and approved
  - view: pay stubs, tax documents (historical)
```

### Walker
**Purpose**: Same as Driver but pedestrian-specific logistics

**Permissions**:
```yaml
# Identical to Driver with these differences:

routes:
  - read: walking routes only (no vehicle routes)
  - navigate: pedestrian-optimized directions

vehicle:
  - NO ACCESS (not applicable)

equipment:
  - read: assigned cart/bag
  - update: equipment condition
```

## 🔄 State Transitions & Visibility

### Timesheet Lifecycle
```
State: OPEN
- Driver can: clock in/out, view hours
- Management sees: real-time hours (not finalized)
- Payroll shows: nothing

State: LOCKED (period ended)
- Driver can: view only
- Management sees: pending approval list
- Payroll shows: nothing

State: APPROVED
- Driver can: view only
- Management sees: approved hours
- Payroll shows: hours sent to ADP
- System action: sync to ADP

State: PROCESSED (ADP completes)
- Driver can: view hours + pay details
- Management sees: finalized payroll report
- Payroll shows: complete pay stub
```

## 🚨 Special Cases & Edge Cases

### Case 1: Disputed Hours
```
Scenario: Driver claims they worked 8 hours, system shows 7.5

Flow:
1. Driver sees discrepancy in "hours worked"
2. Driver submits dispute through app
3. Dispatch/Management receives notification
4. Management reviews clock in/out logs, GPS data
5. Management can:
   - Approve dispute → Manual adjustment with reason
   - Deny dispute → Provide explanation
6. Audit log records all actions
7. If approved, correction syncs to ADP
```

### Case 2: Emergency Route Reassignment
```
Scenario: Driver Marcus calls in sick mid-route

Flow:
1. Dispatch marks Marcus as "unavailable"
2. System shows Marcus's route as "unassigned"
3. Dispatch reassigns route to available driver (Sarah)
4. Sarah's app immediately shows new packages
5. Marcus's timesheet auto-clocks out with note
6. System creates incident report for management review
```

### Case 3: Multi-Role Users
```
Scenario: Person is both Dispatch AND occasionally drives

Solution: Context-based role switching
- User has roles: ["dispatch", "driver"]
- App shows role switcher: "View as: Dispatch | Driver"
- Permissions apply based on active context
- Actions logged with active role
```

## 🔍 Audit & Compliance

### Required Audit Logging
```
ALL actions on these resources must log:
- timesheets (MODIFY, APPROVE, EXPORT)
- payroll (VIEW, EXPORT, CALCULATE)
- employee pay rates (VIEW, MODIFY)
- route assignments (ASSIGN, REASSIGN)
- package delivery status (UPDATE)

Log format:
{
  timestamp: "2026-03-06T10:30:00Z",
  tenant_id: "company_abc",
  user_id: "user_123",
  user_role: "management",
  action: "APPROVE_TIMESHEET",
  resource_type: "timesheet",
  resource_id: "ts_456",
  changes: {before: "pending", after: "approved"},
  ip_address: "192.168.1.1",
  reason: "Verified all clock-ins match GPS data"
}
```

## 📋 Implementation Checklist

- [ ] Database: Add role column to users table
- [ ] Database: Add permissions table for fine-grained control
- [ ] Backend: Create permission decorator for API endpoints
- [ ] Backend: Implement role-based query filters
- [ ] Backend: Build timesheet approval workflow
- [ ] Backend: Create audit logging system
- [ ] Frontend: Role-based UI rendering
- [ ] Frontend: Build timesheet approval interface for management
- [ ] Frontend: Create driver view with hours-only display
- [ ] Testing: Test all permission boundaries
- [ ] Testing: Test state transitions
- [ ] Testing: Test multi-role scenarios
