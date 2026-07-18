/** Role constants for tab gating — in their own module ON PURPOSE.
 *
 * navigation/index imports every screen, and screens import these constants.
 * When they lived in navigation/index, any screen importing them created a
 * require cycle: the screen module evaluates before navigation/index finishes,
 * so the constant is silently `undefined` at that moment (HomeScreen's
 * Field Ops quick-action filter saw roles=undefined and showed the tile to
 * every role). Constants here import nothing, so no cycle is possible.
 */
export const FIELD_ROLES              = ['driver', 'trainer', 'trainee', 'walker'] as const;
export const FIELD_OPS_ROLES          = ['driver'] as const;
// Driver runs the AP workflow (relocate/arrival); crew sees the meet-up point +
// today's assignment. Same "Anchor Point" tab, role-branched component.
export const ANCHOR_POINT_ROLES       = ['driver', 'trainer', 'trainee', 'walker'] as const;
export const PREFERENCES_ROLES        = ['driver', 'walker', 'trainer', 'trainee'] as const;
export const SCHEDULE_ROLES           = ['driver', 'walker', 'trainer', 'trainee'] as const;
// Field staff submit + track schedule-change requests from the Schedule tab's
// "Schedule Changes" sub-tab (ADR-207), so they don't need a separate bottom tab.
// The standalone tab is now the reviewers' approval queue only.
export const SCHEDULE_CHANGE_ROLES    = ['dispatch', 'management', 'admin'] as const;
export const INCIDENT_ROLES           = ['driver', 'walker', 'trainer', 'trainee'] as const;
export const TRAINER_ROLES            = ['trainer'] as const;
export const TRAINEE_ROLES            = ['trainee'] as const;
export const WALKER_ROLES             = ['walker'] as const;
export const LOCATION_PROFILE_ROLES   = ['driver', 'walker', 'trainer', 'trainee'] as const;
// Drivers AND trainers run AP Sort at the anchor point (mobile-first page).
export const ROUTE_SORT_ROLES         = ['driver', 'trainer'] as const;
// Trainers carry routes too (solo wave assignment or the paired trainee's) —
// walkers/trainees reach My Route inside their own dashboards instead.
export const MY_ROUTE_TAB_ROLES       = ['trainer'] as const;
export const DRIVER_SURVEY_ROLES      = ['trainer', 'walker'] as const;
export const GEAR_ROLES               = ['driver', 'walker', 'trainer', 'trainee'] as const;
export const REATTEMPT_ROLES          = ['driver', 'trainer'] as const;
