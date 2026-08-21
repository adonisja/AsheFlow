import React from 'react';
import { useAuth } from '@contexts/AuthContext';
import AnchorPointsScreen from '@screens/AnchorPoints/AnchorPointsScreen';
import TodayAssignmentScreen from '@screens/Home/TodayAssignmentScreen';

/**
 * The "Anchor Point" tab is role-aware:
 *  - Driver: the AP workflow — current anchor point + relocation + arrival
 *    confirm. The INITIAL AP is set in Field Ops (gated behind departure,
 *    ADR-206), not here.
 *  - Everyone else (trainer / walker / trainee): the crew view of today's
 *    assignment — truck, role, pairing, where to meet the driver, the AP's
 *    ETA / arrival status / relocation, and (for a paired trainee) the
 *    "I've arrived" confirmation.
 */
export default function AnchorPointTab() {
  const { hasRole } = useAuth();
  return hasRole('driver') ? <AnchorPointsScreen /> : <TodayAssignmentScreen />;
}
