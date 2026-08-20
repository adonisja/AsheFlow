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
export const MY_ROUTE_TAB_ROLES       = ['trainer'] as const;
export const DRIVER_SURVEY_ROLES      = ['trainer', 'walker'] as const;
export const GEAR_ROLES               = ['driver', 'walker', 'trainer', 'trainee', 'captain'] as const;
export const REATTEMPT_ROLES          = ['driver', 'trainer', 'captain'] as const;
