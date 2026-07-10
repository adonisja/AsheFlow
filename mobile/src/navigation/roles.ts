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
export const ANCHOR_POINT_ROLES       = ['driver'] as const;
export const PREFERENCES_ROLES        = ['driver', 'walker', 'trainer', 'trainee'] as const;
export const SCHEDULE_ROLES           = ['driver', 'walker', 'trainer', 'trainee'] as const;
export const SCHEDULE_CHANGE_ROLES    = ['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin'] as const;
export const INCIDENT_ROLES           = ['driver', 'walker', 'trainer', 'trainee'] as const;
export const TRAINER_ROLES            = ['trainer'] as const;
export const TRAINEE_ROLES            = ['trainee'] as const;
export const WALKER_ROLES             = ['walker'] as const;
export const LOCATION_PROFILE_ROLES   = ['driver', 'walker', 'trainer', 'trainee'] as const;
export const ROUTE_SORT_ROLES         = ['driver'] as const;
export const DRIVER_SURVEY_ROLES      = ['trainer', 'walker'] as const;
