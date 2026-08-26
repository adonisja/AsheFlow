/** Role constants for tab gating — in their own module ON PURPOSE.
 *
 * navigation/index imports every screen, and screens import these constants.
 * When they lived in navigation/index, any screen importing them created a
 * require cycle: the screen module evaluates before navigation/index finishes,
 * so the constant is silently `undefined` at that moment (HomeScreen's
 * Field Ops quick-action filter saw roles=undefined and showed the tile to
 * every role). Constants here import nothing, so no cycle is possible.
 */
/* CAPTAIN (ADR-256 / ADR-274 D19). A captain is a truck's route lead — they run
 * the anchor-point sort, own RTS and reattempts, and answer for the crew. None
 * of the tuples below named them, so a captain logging in got ZERO tabs and
 * could not reach any of the work D5 assigned them.
 *
 * Added only where the captain is the operational lead. Deliberately NOT added
 * to TRAINER_ROLES / TRAINEE_ROLES / WALKER_ROLES — those are training and
 * personal-route surfaces, and D5 moved route-lead authority to captains
 * WITHOUT moving training supervision. */
export const FIELD_ROLES              = ['driver', 'trainer', 'trainee', 'walker', 'captain'] as const;
export const FIELD_OPS_ROLES          = ['driver', 'captain'] as const;
// Driver runs the AP workflow (relocate/arrival); crew sees the meet-up point +
// today's assignment. Same "Anchor Point" tab, role-branched component.
export const ANCHOR_POINT_ROLES       = ['driver', 'trainer', 'trainee', 'walker', 'captain'] as const;
export const PREFERENCES_ROLES        = ['driver', 'walker', 'trainer', 'trainee', 'captain'] as const;
export const SCHEDULE_ROLES           = ['driver', 'walker', 'trainer', 'trainee', 'captain'] as const;
// Field staff submit + track schedule-change requests from the Schedule tab's
// "Schedule Changes" sub-tab (ADR-207), so they don't need a separate bottom tab.
// The standalone tab is now the reviewers' approval queue only.
export const SCHEDULE_CHANGE_ROLES    = ['dispatch', 'management', 'admin'] as const;
export const INCIDENT_ROLES           = ['driver', 'walker', 'trainer', 'trainee', 'captain'] as const;
export const TRAINER_ROLES            = ['trainer'] as const;
export const TRAINEE_ROLES            = ['trainee'] as const;
export const WALKER_ROLES             = ['walker'] as const;
/* LOCATION_PROFILE_ROLES removed with the Locations tab (ADR-274 D21).
 * That screen called /location-profiles/, a router DELETED by ADR-135 when the
 * model went address-first — both its calls 404'd, so it had been dead since
 * that rename. Building intelligence is submitted from MyRouteScreen instead,
 * in context at the stop the walker just completed, which is both the working
 * path and the better one. */
// Drivers AND trainers run AP Sort at the anchor point (mobile-first page).
// D5: route assignment is the captain's. Driver stays (the captain organises
// routes WITH the driver); trainer stays for now — see the trainer->captain
// audit in the D19 journal, which reports rather than moves it.
export const ROUTE_SORT_ROLES         = ['driver', 'trainer', 'captain'] as const;
// Trainers carry routes too (solo wave assignment or the paired trainee's) —
// walkers/trainees reach My Route inside their own dashboards instead.
//
// CAPTAIN added (ADR-276 follow-up): a captain occasionally carries a route of
// their own, and routinely carries the reattempts walkers could not complete.
// Without this tab they had no mobile route screen at all — and therefore no
// way to submit building intelligence from the stop they were standing at,
// which is the one thing the operator called them "the walking banks" for.
//
// /me/routes returns the whole TRUCK for a captain (they are truck-scoped), but
// the screen filters to routes where the caller is executor or supervisor —
// verified on staging: a 2-route truck showed the captain only their own.
export const MY_ROUTE_TAB_ROLES       = ['trainer', 'captain'] as const;
export const DRIVER_SURVEY_ROLES      = ['trainer', 'walker'] as const;
export const GEAR_ROLES               = ['driver', 'walker', 'trainer', 'trainee', 'captain'] as const;
export const REATTEMPT_ROLES          = ['driver', 'trainer', 'captain'] as const;
// ADR-277 D3: the truck-scoped building page. Field roles collect, sign-off
// roles confirm — the same union that gates the endpoint. Drivers are absent
// for the reason _allow_delivery already records: they do not walk blocks or
// assess buildings.
export const TRUCK_BUILDINGS_ROLES    = ['walker', 'trainer', 'trainee', 'captain', 'dispatch'] as const;

// ADR-291: entering tote addresses is route-lead work — a captain walks the
// truck reading addresses off packages. Driver included because a solo driver
// runs the truck when no captain is crewed; dispatch for station-side
// correction. Walkers deliberately absent: they carry the routes this produces,
// they do not define them.
export const TOTE_ADDRESS_ROLES     = ['captain', 'driver', 'dispatch'] as const;

/** ADR-297: who sees the workforce "My Route" tab.
 *
 * The people who WALK a route in workforce mode. Deliberately wider than
 * WALKER_ROLES: a trainee walks their own route (phase 4 solo, ADR-145) and a
 * trainer walks one like anyone else on a short-staffed day.
 *
 * Distinct from MY_ROUTE_TAB_ROLES, which is full mode's screen — a different
 * shape (stops, not totes) gated on a different capability. */
export const WORKFORCE_ROUTE_ROLES  = ['walker', 'trainee', 'trainer'] as const;
