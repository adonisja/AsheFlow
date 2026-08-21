import { useAuth } from '../contexts/AuthContext';
import type { Role } from '../config/navConfig';

/**
 * useCan — capability checks for in-page controls (access-control audit).
 *
 * SECURITY NOTE: this is a UX/consistency layer ONLY. It hides or disables
 * controls a role cannot use so users never see dead buttons. It is NOT a
 * security boundary — the roles come from the client-held JWT and the logic
 * runs in the browser, so it can be trivially bypassed. Every action is
 * enforced server-side by RoleChecker (see backend tests/test_guard_coverage).
 * Rule: gate the BUTTON with useCan, gate the ENDPOINT with RoleChecker —
 * always both, never one.
 *
 * Capability role sets mirror the backend guards so a control and its endpoint
 * share one definition. When a backend guard changes, update the matching
 * capability here.
 */

// Backend role constants (CLAUDE.md role model), mirrored for the UI.
const DISPATCH_MGMT: Role[] = ['dispatch', 'management', 'admin'];
const CAPTAIN: Role[]       = ['trainer', 'driver', 'dispatch', 'management', 'admin'];
const DRIVER_ONLY: Role[]   = ['driver'];
const MGMT_ONLY: Role[]     = ['management', 'admin'];

/** Capability → the roles the BACKEND allows for that action. Keep in sync
 *  with the endpoint's RoleChecker (the endpoint is the real gate). */
export const CAPABILITIES = {
  // Station / dispatch operations
  runSort:            DISPATCH_MGMT,   // note: /sort page also allows driver (own check-off)
  editManifest:       DISPATCH_MGMT,   // POST/PATCH /dispatch/manifest (allow_dispatch_mgmt)
  confirmAnchorPoint: DISPATCH_MGMT,   // PATCH /anchor-points/{id}/confirm (allow_dispatch)
  submitAnchorPoint:  DRIVER_ONLY,     // POST /anchor-points/ (allow_driver)

  // AP Sort / walker routes (_allow_captain — ADR-151 includes management)
  commitSort:         CAPTAIN,
  distributeWave:     CAPTAIN,
  reassignRoute:      CAPTAIN,
  resolveMisroute:    CAPTAIN,

  // Field ops (driver writes / oversight reads — ADR-017)
  submitFieldOps:     DRIVER_ONLY,     // check-in/departure/inspection/fuel/rating

  // Reviews / approvals (management supervisory — ADR-016)
  resolveIncident:    DISPATCH_MGMT,   // PATCH /incidents/{id}/resolve (allow_management)
  reviewScheduleChange: DISPATCH_MGMT, // approve/reject schedule changes
  approveTimeOff:     DISPATCH_MGMT,   // PATCH /time-off-requests/{id}/approve
  approveGear:        MGMT_ONLY,       // gear request approval

  // Building profiles (ADR-151)
  lockBuildingProfile:  DISPATCH_MGMT, // POST /building-profiles/{id}/lock
  anchorBuildingProfile: DISPATCH_MGMT,
} as const;

export type Capability = keyof typeof CAPABILITIES;

export interface CanApi {
  /** True if the current user's roles satisfy the capability's backend role set. */
  can: (capability: Capability) => boolean;
  /** Raw role predicate for one-off cases not worth a named capability. */
  hasRole: (...roles: Role[]) => boolean;
  groups: string[];
}

export function useCan(): CanApi {
  const { groups } = useAuth();
  const roleSet = new Set(groups as Role[]);
  return {
    can: (capability) => CAPABILITIES[capability].some(r => roleSet.has(r)),
    hasRole: (...roles) => roles.some(r => roleSet.has(r)),
    groups,
  };
}
