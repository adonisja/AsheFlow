# Engineering Journal: March 31, 2026

**Session Start Time**: March 31, 2026, 08:43 PM EST (GMT-5, NYC)
**Session End Time**: April 1, 2026, 05:17 AM EST (GMT-5, NYC)

## Goal for the Session
Design the initial Data Model and logical architecture for the Daily Route Dispatch System. We need to define the core entities (Users, Trucks, Assignments) and how they relate to the business constraints (Ban/Fav lists, Role limits).

## Problems Encountered
* None yet.

## Solutions & Procedures

### Data Model Design — Dispatch System

Through Socratic discussion, arrived at the following 6-table data model for the Daily Truck Assignment system:

| Table | Responsibility |
|---|---|
| `employees` | Static identity record: id, name, discord_id, role, is_active |
| `trucks` | Static truck entities: id, name/number |
| `truck_assignments` | One record per truck per day: truck_id, date |
| `assignment_members` | Junction table linking employees to assignments with role (driver/trainer/walker) |
| `employee_off_days` | One row per off-day per employee: employee_id, day_of_week |
| `employee_relationships` | Ban/fav links between employees: employee_id, target_employee_id, type (ban/fav) |

### Key Architectural Decisions

1. **`gen_random_uuid()` over `uuid_generate_v4()`**: Chose the built-in PostgreSQL 13+ function over the `uuid-ossp` extension equivalent. Rationale: non-technical dispatch personnel will manage this system after handoff — eliminating the `CREATE EXTENSION` dependency removes one failure point in fresh deployments. Fewer moving parts = lower operational risk.

2. **Junction table over fixed columns**: Storing walkers as `walker_1_id`, `walker_2_id`... columns was rejected. Variable membership is modeled via `assignment_members` — one row per person per assignment.
2. **Derived state over stored state**: `previous_truck` field on employee was rejected. Yesterday's truck is derived by querying `assignment_members` for date = yesterday. No data duplication, full history preserved.
3. **Atomic values over lists**: Off-days stored as one row per day, not as a list/array in a single column (1NF compliance).
4. **Single relationship table**: Ban and favorites lists collapsed into one `employee_relationships` table with a `type` column rather than two separate tables.

### Final SQL Schema Produced

```sql
CREATE TABLE employees (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name          VARCHAR(255) NOT NULL,
    discord_id    VARCHAR(100) NOT NULL UNIQUE,
    role          VARCHAR(50)  NOT NULL CHECK (role IN ('driver', 'trainer', 'walker')),
    is_active     BOOLEAN      NOT NULL DEFAULT true
);

CREATE TABLE trucks (
    id        UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    name      VARCHAR(100) NOT NULL UNIQUE,
    is_active BOOLEAN      NOT NULL DEFAULT true
);

CREATE TABLE truck_assignments (
    id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    truck_id  UUID        NOT NULL REFERENCES trucks(id),
    date      DATE        NOT NULL,
    status    VARCHAR(50) NOT NULL DEFAULT 'planned'
                          CHECK (status IN ('planned', 'active', 'completed'))
);

CREATE TABLE assignment_members (
    id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id UUID        NOT NULL REFERENCES truck_assignments(id),
    employee_id   UUID        NOT NULL REFERENCES employees(id),
    role          VARCHAR(50) NOT NULL CHECK (role IN ('driver', 'trainer', 'walker'))
);

CREATE TABLE employee_off_days (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id UUID        NOT NULL REFERENCES employees(id),
    day_of_week VARCHAR(10) NOT NULL CHECK (day_of_week IN ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'))
);

CREATE TABLE employee_relationships (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id        UUID        NOT NULL REFERENCES employees(id),
    target_employee_id UUID        NOT NULL REFERENCES employees(id),
    relationship_type  VARCHAR(10) NOT NULL CHECK (relationship_type IN ('ban', 'fav'))
);

-- Performance indexes
CREATE INDEX idx_assignment_members_assignment_id ON assignment_members(assignment_id);
CREATE INDEX idx_assignment_members_employee_id   ON assignment_members(employee_id);
CREATE INDEX idx_truck_assignments_date           ON truck_assignments(date);
```

### Additional Architectural Notes
- **Max-2 ban/fav enforcement**: Database cannot enforce the "max 2 walkers per driver" constraint via SQL alone — requires counting existing rows. This rule lives in the FastAPI application layer.
- **Soft deletes on employees and trucks**: `is_active` flag preserves history and prevents foreign key breakage on retirement.

## Key Takeaways
* Learned about one-to-many relationships and the importance of junction tables to bridge the gap caused by the fixed-column anti-pattern — having variable membership on a fixed-column table leads to excessive NULLs and unmaintainable schema.
* Learned that storing derived state (e.g. `previous_truck`) is an anti-pattern — if the data can be answered by a query against existing records, don't duplicate it into a field.
* Learned about First Normal Form (1NF) — values in a column must be atomic (single values), not lists. Variable multi-value data belongs in its own table.
* Learned about database indexes — PRIMARY KEY and UNIQUE columns are auto-indexed; foreign keys and frequently filtered columns need manual indexes. Trade-off: faster reads, slightly slower writes.
* Learned the distinction between database-enforceable rules (CHECK, UNIQUE, NOT NULL) vs. application-layer rules (complex counting logic like max-2 ban lists).
