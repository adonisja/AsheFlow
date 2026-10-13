import React, { useCallback, useEffect, useMemo, useState } from 'react';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { useTabSwitch } from '@navigation/index';
import { resolveActionRoute } from '@navigation/actionRoutes';
import NotificationGate from './NotificationGate';
import ActionPrompt from './ActionPrompt';
import GraduationPrompt from './GraduationPrompt';
import OperatingModeChangePrompt from './OperatingModeChangePrompt';

/**
 * Picks the one interruptive notification to show, if any (ADR-494). Twin of
 * the web InterruptiveHost.
 *
 * ## One at a time, gates first
 *
 * Two RN Modals at once stack, and the second is invisible until the first
 * closes — so a gate under a prompt would silently not apply. Showing exactly
 * one, gate first, makes the order a decision rather than whatever the array
 * happened to hold.
 *
 * ## What this does NOT decide
 *
 * Whether something is a gate or a prompt is the server's answer (D6). This
 * reads `channels` and renders. No expiry check, no deadline arithmetic, no
 * "is the role guide seeded" test — all three already happened server-side, and
 * a second copy here is the drift D6 exists to prevent.
 *
 * ## The one thing it DOES decide
 *
 * Whether this surface can reach the action's destination.
 * `SPEC.actions[].route` is a web path and mobile navigates by tab key, so
 * `resolveActionRoute` translates it against the company's capability list —
 * `/my-route` is two different tabs depending on operating mode. A null result
 * means no mobile screen exists, and the children render no button rather than
 * one that goes nowhere.
 *
 * ## Why it fetches rather than reading a context
 *
 * Mobile has no NotificationContext; NotificationsScreen fetches per-screen.
 * Rather than introduce a second polling scheme, this does one fetch on mount
 * — mounted in MainShell, so once per session, matching MfaGracePrompt's
 * once-per-launch behaviour (ADR-381 D2). An interruptive notification that
 * arrives mid-session reaches the person on their next launch, which is the
 * right cadence for "your role changed": it is not an injury alert.
 */

type Interruptive = {
  id: string;
  type: string;
  label: string;
  message: string;
  channels: string[];
  actions: { label: string; route: string; style: string }[];
};

export default function InterruptiveHost() {
  const { user, capabilities } = useAuth();
  const { fetchId } = useEmployeeId();
  const switchTab = useTabSwitch();
  const [items, setItems] = useState<Interruptive[]>([]);
  const [done, setDone] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!user) return;
      const eid = await fetchId();
      if (!eid || cancelled) return;
      try {
        const res = await apiClient.get(`/notifications/${eid}?limit=50`);
        if (cancelled) return;
        const rows: Interruptive[] = res.data ?? [];
        setItems(rows.filter(n =>
          n.channels?.includes('gate') || n.channels?.includes('prompt'),
        ));
      } catch {
        // Silent. An interruptive notification that cannot be fetched should
        // not surface an error over the whole app — the person still gets it
        // in the Notifications tab, and on the next launch.
        setItems([]);
      }
    })();
    return () => { cancelled = true; };
  }, [user, fetchId]);

  const features = capabilities?.features ?? [];

  const target = useMemo(() => {
    const live = items.filter(n => !done.has(n.id));
    // Gates before prompts, deliberately — see the note above.
    return (
      live.find(n => n.channels.includes('gate')) ??
      live.find(n => n.channels.includes('prompt')) ??
      null
    );
  }, [items, done]);

  const finish = useCallback(() => {
    if (target) setDone(prev => new Set(prev).add(target.id));
  }, [target]);

  if (!target) return null;

  // Translate the web path to a tab key. Null = no mobile surface, and the
  // children must then render no button.
  const route = target.actions[0]?.route;
  const tabKey = route ? resolveActionRoute(route, features) : null;
  const onNavigate = tabKey ? () => switchTab(tabKey) : null;

  if (target.channels.includes('gate')) {
    return <NotificationGate notification={target} onDone={finish} onNavigate={onNavigate} />;
  }

  switch (target.type) {
    case 'graduation':
      return <GraduationPrompt notification={target} onDone={finish} onNavigate={onNavigate} />;
    case 'operating_mode_change':
      return <OperatingModeChangePrompt notification={target} onDone={finish} onNavigate={onNavigate} />;
    default:
      // ADR-505 D4. Was `return null`: every other prompt rendered nothing, and
      // as the FIRST prompt it hid every prompt behind it. Reproduced on this
      // emulator 2026-10-13: a timecard_mismatch (degraded to a prompt) showed
      // no sheet, and a graduation that rendered a minute earlier vanished.
      return <ActionPrompt notification={target} onDone={finish} onNavigate={onNavigate} />;
  }
}
