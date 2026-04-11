# ADR-001: Role-Based Favorite List System

**Date:** April 5, 2026
**Status:** Accepted (revised April 5, 2026)

---

## Context

The dispatch system allows employees to maintain a "favorite" list — people they prefer to work with. These preferences influence (but do not guarantee) truck assignments through weighted random selection.

The original design had a flat limit of 2 favorites per employee, regardless of who they were favoriting or what role either party held. As the dispatch algorithm was designed in detail, it became clear this flat limit was insufficient.

The delivery operation has three distinct roles with different responsibilities:
- **Driver** — operates the truck, assigned first, notified earliest
- **Trainer** — supervises walkers, assigned second
- **Walker** — performs deliveries on foot, assigned last


**2026-04-09 Update:**
- Only employees with the roles `driver`, `trainer`, or `walker` can favorite or ban others. Roles such as `management`, `admin`, `dispatch`, and `trainee` are exempt from being favorited or banned, and do not appear in the selection lists. This is enforced in both backend (seed logic, API) and frontend (Preferences UI).

These roles interact differently on a truck. A driver's preference for a specific trainer is a stronger signal than a walker's preference for another walker. The flat limit treated all preferences equally and allowed nonsensical combinations (e.g. a driver favoriting two other drivers, despite drivers never sharing a truck).

---

## Considered Options

### Option 1: Flat limit of 2 favs per employee (original)
Any employee can fav any other 2 employees, regardless of role.

**Pros:** Simple to implement and enforce.
**Cons:** Allows meaningless pairings (driver→driver). Doesn't reflect how crews actually work. All preferences weighted equally despite different operational significance.

### Option 2: Role-based limits with no weighting distinction
Enforce role-specific fav limits but apply the same probability boost to all favs.

**Pros:** Prevents invalid pairings. Still relatively simple.
**Cons:** Doesn't reflect the different influence each role has on assignment outcomes.

### Option 3: Role-based limits with role-weighted probability boosts (chosen)
Enforce role-specific limits AND apply different boost magnitudes based on who is doing the favoriting.

| Employee Role | Can Fav | Limit | Role Boost Factor |
|---|---|---|---|
| Driver | Trainer | 1 | 0.70 |
| Driver | Walker | 2 | 0.70 |
| Driver | Driver | 0 | N/A (not allowed) |
| Trainer | Driver | 1 | 0.50 |
| Trainer | Trainer | 1 | 0.50 |
| Trainer | Walker | 2 | 0.50 |
| Walker | Driver | 1 | 0.30 |
| Walker | Trainer | 1 | 0.30 |
| Walker | Walker | 2 | 0.30 |

**Boost logic:** Driver favs carry the most weight (0.70) since drivers are assigned first and their preferences set the context for the rest of the crew. Trainer favs carry moderate weight (0.50). Walker favs carry the least (0.30) since they are assigned last and have the least influence over crew composition.

---

## Weight Calculation Formula

**Initial base weight per truck:**
```
base_per_truck = 1.0 / num_trucks
# e.g. 5 trucks → 0.20 each, 7 trucks → 0.1429 each
```

**Applying a fav boost (one-directional):**
```
boosted_weight = current_weight + (current_weight × role_boost_factor)
# e.g. at 5 trucks: 0.20 + (0.20 × 0.70) = 0.34
```

**Redistributing non-favored trucks:**
When one truck's weight is boosted, the remaining trucks each drop proportionally:
```
other_truck_weight = (1.0 - boosted_weight) / (num_trucks - 1)
# e.g. boosted to 0.34 → remaining 4 trucks = (1 - 0.34) / 4 = 0.165 each
```

**Stacking boosts across passes:**
Trainer and walker boosts apply on top of already-adjusted weights from prior passes — not on the original base. Each pass compounds the existing weight:
```
# Driver pass sets trainer weight for Truck A to 0.34
# Trainer pass then applies to that 0.34:
0.34 + (0.34 × 0.50) = 0.51
```

**Cap:** No truck's weight ever exceeds **0.85** regardless of compounding — prevents near-deterministic assignment.

---

## Bi-directional and Tri-directional Mutual Bonus

When a fav relationship is **mutual**, a flat bonus is added to the boosted weight **after** the standard boost is applied. Mutual bonuses do not stack — tri-directional overrides bi-directional.

| Pairing type | Condition | Flat bonus |
|---|---|---|
| One-directional | Only one side has the other as fav | +0.00 |
| Bi-directional | Both sides fav each other | +0.10 (if result < 0.85) |
| Tri-directional | All three (driver↔trainer↔walker) fav each other | +0.20 (if result < 0.85) |

**Example — bi-directional at 5 trucks:**
```
Driver pass:  0.20 + (0.20 × 0.70) = 0.34
Mutual bonus: 0.34 + 0.10 = 0.44
Trainer pass: 0.44 + (0.44 × 0.50) = 0.66
# Non-favored 4 trucks = (1 - 0.66) / 4 = 0.085 each
```

**Example — bi-directional at 7 trucks:**
```
Driver pass:  0.1429 + (0.1429 × 0.70) = 0.2429
Mutual bonus: 0.2429 + 0.10 = 0.3429
Trainer pass: 0.3429 + (0.3429 × 0.50) = 0.514
# Non-favored 6 trucks = (1 - 0.514) / 6 = 0.081 each
```

**Tri-directional rationale:** A driver↔trainer↔walker mutual triangle represents the strongest possible crew bond. The +0.20 bonus is intentional — it allows the business to benefit from the efficiency of a strongly linked team while also making such groupings easy to identify and audit if a pattern of misconduct needs to be disrupted.

**Cap behavior:** If applying the mutual bonus would push the weight above 0.85, the weight is set to exactly 0.85 — the bonus is not partially applied.

---

## Conflict Resolution — Multiple Employees Favoring the Same Candidate

When multiple already-assigned crew members have the same unassigned candidate in their fav list:

1. Check if the candidate has any of them in their own fav list
2. If **one mutual match** → only that person's boost applies (with bi-directional bonus if mutual), all others nullified
3. If **no mutual match** → candidate's own preferred crew member gets a reduced boost (role_factor × 0.5); the other crew members with the candidate on their fav list split the remaining role_factor × 0.5 evenly between their trucks

This prevents a popular employee from receiving compounded boosts that would make assignment near-deterministic.

---

## Three-Pass Walker Weight Updates

Weight adjustments happen in three distinct passes:

1. **Driver pass** — after drivers are placed, boost weights for everyone on each driver's fav list toward that driver's truck. Resolve multi-driver conflicts immediately.
2. **Trainer pass** — sequential weighted trainer assignment. After each trainer placement, update weights for remaining unassigned employees (trainers and walkers) who have that trainer in their fav list.
3. **Walker pass** — single weighted roll per walker against the fully populated weight table from passes 1 and 2.

Walker weight updates from trainer fav lists are applied in pass 2, not pass 3. By the time walkers roll, their weight table already reflects all driver and trainer placements.

---

## Ban Override Rule — Fav Pull vs. Walker Ban

A hard conflict arises when a candidate is heavily pulled toward a truck (driver/trainer fav) but an employee already on that truck has the candidate on their ban list.

**Decision tree (evaluated in order):**

1. Is the banning employee a **driver or trainer**? → **keep ban, block candidate** (drivers and trainers have structural authority)
2. Is the banning employee a **walker** AND on any driver/trainer's fav list? → **keep ban, block candidate** (walker has earned their spot through a fav relationship)
3. Is the banning employee a **walker** AND NOT on any driver/trainer's fav list, BUT the **candidate IS** on a driver/trainer's fav list? → **override ban — assign candidate, reassign the banning walker**
4. All other cases → **keep ban, block candidate**

**Rationale:** Drivers and trainers have structural authority over their truck. A walker's ban can only hold if that walker has an established relationship with the crew (via driver/trainer fav). Otherwise, a fav-pulled candidate takes priority and the walker is reassigned.

**Note:** This rule only applies when candidate X has a strong fav pull toward the truck. If the candidate has no fav relationship to the truck, standard ban logic applies in all cases.

---

## Trade-offs

**Complexity:** Role-based limits require a JOIN query to count existing favs by target role. The weight calculation system with three passes and conflict resolution is non-trivial but well-bounded — at 7 trucks and 65 employees, all calculations complete in milliseconds.

**Auditability:** The tri-directional bonus makes strongly linked crews easy to identify in the assignment logs. This is a feature, not a bug — it supports both efficiency recognition and misconduct detection.

**Maintainability:** Base boost factors (0.70/0.50/0.30) and flat bonuses (+0.10/+0.20) should be extracted to a constants file. Changing one value automatically scales all derived weights.

---

## Decision

**Option 3 — Role-based limits with role-weighted probability boosts, additive mutual bonuses, and three-pass weight calculation.**

Reasons:
1. Drivers never share a truck, so driver→driver favs are operationally meaningless. Blocking them keeps data clean.
2. Role-weighted boosts reflect the real hierarchy of influence in crew assembly — drivers set the context, trainers refine it, walkers fill remaining slots.
3. The additive formula (`weight + (weight × factor)`) compounds correctly across passes without losing the proportional relationship between trucks.
4. Flat mutual bonuses (+0.10/+0.20) are meaningful at real operating scale (5-7 trucks) without being heavy-handed — verified through worked examples.
5. Tri-directional crews benefit the business operationally and are auditable — intentional design.
6. No assignment is guaranteed — only made more probable. On low-volume days, the system must fill trucks over honoring preferences.

---

## Consequences

- `FAV_LIMITS` dict must be kept in sync between the router (`employee_relationships.py`) and the seed script (`seed.py`).
- Any future role additions require updating `FAV_LIMITS` in both locations.
- Base boost factors and flat bonuses must be extracted to a constants file — not hardcoded inline.
- The dispatch algorithm must implement three-pass weight calculation, bi/tri detection, conflict resolution, and ban override logic — non-trivial, must be unit tested thoroughly.
- Open question: confirm with the business whether base boost factors need adjustment after observing real dispatch outcomes.

---

## Learnings & Growth

- Flat limits seem simple but hide implicit assumptions about how entities relate. Always model constraints in terms of the business domain, not just "max N."
- Role-based validation belongs in the router (business rule), not the database schema (structural constraint).
- Working through concrete numeric examples revealed formula errors that abstract descriptions missed — the additive formula vs. multiplicative replacement distinction only became clear when checking actual numbers.
- Flat mutual bonuses scale better than multipliers at larger fleet sizes — the +0.10/+0.20 approach was validated through 5-truck and 7-truck worked examples.
- The 0.85 cap was identified as necessary during the math walkthrough — without it, compounded boosts across three passes could reach near-100%, removing meaningful randomness.
- The tri-directional bonus serves dual purpose: operational efficiency and auditability. Business-aligned design decisions often have non-obvious secondary benefits.
