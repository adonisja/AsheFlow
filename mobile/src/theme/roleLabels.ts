/**
 * Role display names. Shared with frontend/src/utils/roleLabels.ts byte-for-byte below this comment
 * (scripts/check_shared_copies.py): a role named one way on the phone and
 * another on the web reads as two different jobs.
 */
export const ROLE_LABELS: Record<string, string> = {
  driver:           'Driver',
  walker:           'Walker',
  trainer:          'Trainer',
  trainee:          'Trainee',
  admin:            'Admin',
  management:       'Management',
  dispatch:         'Dispatch',
  // ADR-256 / ADR-264. Callers do `ROLE_LABELS[r] ?? r`, so a missing entry
  // renders the raw enum — a driver trainee saw the literal
  // "driver_trainee", underscore and all.
  captain:          'Captain',
  field_supervisor: 'Field Supervisor',
  driver_trainee:   'Driver Trainee',
};

/** A role's display name, falling back to the raw value rather than nothing. */
export function roleLabel(role: string | null | undefined): string {
  if (!role) return '';
  return ROLE_LABELS[role] ?? role;
}
