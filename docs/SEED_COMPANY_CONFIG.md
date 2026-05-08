# Seed Company Configuration — DSP Test Company

This document captures all hardcoded values that were live in the single-tenant
version of AsheFlow before the multi-tenant migration. These values become the
seed row in `company_config` for the first test company and serve as the
reference baseline for any new company onboarding.

**Do not delete this file.** It is the authoritative record of what "default"
means for each config field.

---

## Company identity

| Field | Value | Notes |
|---|---|---|
| `name` | DSP Test Company | Placeholder — replace with real DSP name |
| `slug` | `dsp-test` | URL-safe identifier |
| `amazon_dsp_code` | _(not yet collected)_ | Amazon-assigned DSP station code (e.g. `DLAX1`) |
| `timezone` | `America/New_York` | Assumed from AWS region `us-east-2` |

---

## Dispatch algorithm weights

These control how the auto-dispatch engine scores and ranks crew members.
All values sourced from `backend/app/services/constants.py`.

| Field | Value | Source |
|---|---|---|
| `dispatch_weight_driver` | `0.70` | `ROLE_BOOST["driver"]` |
| `dispatch_weight_trainer` | `0.50` | `ROLE_BOOST["trainer"]` |
| `dispatch_weight_walker` | `0.30` | `ROLE_BOOST["walker"]` |
| `dispatch_mutual_bonus` | `0.10` | `MUTUAL_BONUS["bidirectional"]` |
| `dispatch_tridirectional_bonus` | `0.20` | `MUTUAL_BONUS["tridirectional"]` |
| `dispatch_consecutive_penalty` | `0.05` | `CONSECUTIVE_PENALTY` |
| `dispatch_weight_cap` | `0.85` | `CAP` |

---

## Crew requirements per truck

Sourced from `backend/app/services/constants.py`.

| Field | Value | Source |
|---|---|---|
| `min_trainers_per_truck` | `2` | `MIN_TRAINERS_PER_TRUCK` |
| `min_walkers_per_truck` | `3` | `MIN_WALKERS_PER_TRUCK` |

---

## Training rules

| Field | Value | Source | Meaning |
|---|---|---|---|
| `graduation_assignments` | `5` | `graduate_trainees.py:53` (`assignment_count < 5`) | Trainee graduates to Walker after this many completed dispatch assignments |
| `debt_escalation_threshold` | `3` | `constants.py:DEBT_ESCALATION_THRESHOLD` | Days a mandatory training task can be carried as debt before escalating to management |
| `phase4_pass_score` | `90.0` | `score_phase4.py:PASS_THRESHOLD` | Minimum percentage score to pass Phase 4 practical observation |
| `underperforming_trainer_threshold` | `3` | `record_trainer_mark.py:UNDERPERFORMING_MARK_THRESHOLD` | Number of distinct trainees a trainer must have marks against before the underperforming notification fires to management |
| `max_training_phase` | `4` | `constants.py:MAX_TRAINING_PHASE` | Highest regular curriculum phase (Phase 5 is remediation-only, system-generated) |

---

## Operations timing

These were not configurable in v1 — they are the implicit assumptions baked
into the system. Collect actual values from the DSP before going live.

| Field | Assumed Value | Notes |
|---|---|---|
| `shift_start` | _(not set — collect from DSP)_ | Time drivers are expected at station |
| `shift_end` | _(not set — collect from DSP)_ | Expected return time |
| `checkin_open` | _(not set — collect from DSP)_ | Earliest time check-in is accepted |
| `checkin_close` | _(not set — collect from DSP)_ | Latest time check-in is accepted |
| `rating_window_hours` | `6` | `config.py:rating_window_hours` — hours after driver departure that walker ratings are accepted |
| `invite_expiry_days` | `7` | `config.py:invite_expiry_days` — days before an unverified account is auto-deleted |

---

## Walker rating anomaly detection

| Field | Value | Source |
|---|---|---|
| `flag_threshold` | `1.0` | `field_ops.py:FLAG_THRESHOLD` — star deviation from group average that triggers a flag |

---

## Vehicle inspection checklist

Sourced from `backend/app/models/field_ops.py`. These are the default items
for both pre-trip and EOD inspections.

```
tires
lights
mirrors
brakes
fluids
horn
wipers
seatbelts
cargo_security
fuel_level
```

Inspection types: `pre_trip`, `eod`

---

## Station arrival staging items

Sourced from `backend/app/models/station_arrival.py`.

```
totes
ov_packages
phones_rabbits
chargers
```

Arrival types: `loading`, `return`

---

## Incident categories and severity

Sourced from `backend/app/models/incident.py`.

**Categories:**
```
vehicle
injury
stolen_packages
customer_complaint
route_issue
crew_conduct
safety_hazard
other
```

**Severity levels:**
```
info
warning
critical
```

---

## Driver mid-shift check-ins

| Field | Value | Source |
|---|---|---|
| `driver_checkin_count` | `4` | `driver_check_in.py` — check-ins numbered 1 through 4 per shift |

---

## Notes for migration

- When the `company_config` table is created, insert one row using all the
  numeric values above for the seed company.
- Fields marked "_(not set — collect from DSP)_" should be `NULL` initially
  and filled in via the company admin config screen before going live.
- The inspection checklist, staging items, and incident categories will be
  seeded as rows in their respective lookup tables (`company_inspection_items`,
  `company_staging_items`, `company_incident_categories`) using the lists above.
