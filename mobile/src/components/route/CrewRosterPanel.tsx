/**
 * The captain's Field Ops body: account for the crew (ADR-319).
 *
 * A captain used to open Field Ops and get a header over nothing — the screen
 * puts its whole body behind `isDriver`, so a captain passed the tab gate,
 * reached the screen, and matched no render branch.
 *
 * The driver's 19 steps are a vehicle-and-shift sequence (inspection, fuel,
 * departure, station return) and a captain performs none of them. What a captain
 * does at the truck is account for PEOPLE: who showed, who did not, and which
 * route each one is walking.
 *
 * WHY "ARRIVED" AND NOT "PRESENT"
 * -------------------------------
 * present/late/early are DERIVED server-side from arrival time against the
 * AP-established reference (ADR-198), so a captain cannot pick "late" — and
 * should not. `RollCallCreate` carries `{employee_id, date, notes, ncns}` with
 * no status field: the captain records WHETHER someone showed, and the clock
 * decides whether it was late. The row then shows what the server decided.
 *
 * WORKFORCE MODE ONLY (D0)
 * ------------------------
 * The roster half is mode-agnostic — roll call is not package-coupled. The route
 * half is not: `assigned_to` names a person against a route the WORKFORCE sort
 * built, and full mode assigns stops from a manifest instead. Full mode's
 * captain workflow is a separate design.
 */
import React, { useState } from 'react';
import { ActivityIndicator, Text, TouchableOpacity, View } from 'react-native';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { Badge, tick, MIN_TARGET } from '@components/ui/primitives';

export type RosterMember = { id: string; name: string; role: string };

type Props = {
  crew: RosterMember[];
  /** employeeId → server-derived status (early|present|late|ncns). */
  rollCall: Record<string, string>;
  /** employeeId → route number. Absent for a member with no route yet. */
  routeByEmployee: Record<string, number>;
  today: string;
  onChanged: () => void;
};

/** Which badge tone a server-derived status earns. `pending` is deliberately
 *  neutral, not a warning: nobody has failed yet, they simply have not been
 *  accounted for. */
const TONE: Record<string, 'success' | 'warning' | 'danger' | 'muted'> = {
  early: 'success', present: 'success', late: 'warning', ncns: 'danger',
};

export default function CrewRosterPanel({
  crew, rollCall, routeByEmployee, today, onChanged,
}: Props) {
  const c = useColors();
  const s = styles(c);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = async (employeeId: string, ncns: boolean) => {
    setBusy(employeeId);
    setError(null);
    try {
      // No status field on purpose — the server derives present/late/early from
      // the arrival time (ADR-198). We only say whether they showed.
      await apiClient.post('/roll-call', {
        employee_id: employeeId, date: today, ncns,
      });
      tick();
      onChanged();
    } catch (e: unknown) {
      setError(errorText(e, 'Could not record that.'));
    } finally {
      setBusy(null);
    }
  };

  if (crew.length === 0) {
    return (
      <View style={s.empty}>
        <Text style={s.emptyTitle}>No crew assigned yet</Text>
        <Text style={s.emptyBody}>
          Once dispatch assigns your truck, your crew appears here to be accounted for.
        </Text>
      </View>
    );
  }

  return (
    <View style={s.wrap}>
      <Text style={s.heading}>Crew roster</Text>
      <Text style={s.sub}>
        Mark each person as they arrive. Late is worked out from the time — you
        only say whether they showed.
      </Text>
      {error ? <Text style={s.error}>{error}</Text> : null}

      {crew.map(m => {
        // ADR-319 D4 — a member with no roll-call row renders as PENDING, never
        // omitted. Dropping them would let a captain confirm a roster that
        // quietly lost someone who never showed.
        const status = rollCall[m.id] ?? 'pending';
        const route = routeByEmployee[m.id];
        const done = status !== 'pending';
        return (
          <View key={m.id} style={s.row}>
            <View style={s.who}>
              <Text style={s.name}>{m.name}</Text>
              <Text style={s.meta}>
                {m.role}
                {route != null ? ` · Route ${route}` : ' · no route yet'}
              </Text>
            </View>

            {busy === m.id ? (
              <ActivityIndicator />
            ) : done ? (
              <Badge tone={TONE[status] ?? 'muted'} size="sm">{status}</Badge>
            ) : (
              <View style={s.actions}>
                <TouchableOpacity
                  onPress={() => submit(m.id, false)}
                  style={[s.act, { borderColor: c.success }]}
                  accessibilityRole="button"
                  accessibilityLabel={`Mark ${m.name} arrived`}
                >
                  <Text style={[s.actText, { color: c.success }]}>Arrived</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => submit(m.id, true)}
                  style={[s.act, { borderColor: c.danger }]}
                  accessibilityRole="button"
                  accessibilityLabel={`Mark ${m.name} no-call no-show`}
                >
                  <Text style={[s.actText, { color: c.danger }]}>NCNS</Text>
                </TouchableOpacity>
              </View>
            )}
          </View>
        );
      })}
    </View>
  );
}

const styles = (c: ThemeColors) => ({
  wrap: { paddingHorizontal: spacing.lg, paddingTop: spacing.md },
  heading: {
    color: c.foreground, fontSize: fontSize.lg, fontWeight: fontWeight.bold,
  },
  sub: {
    color: c.mutedForeground, fontSize: fontSize.sm,
    marginTop: spacing.xs, marginBottom: spacing.md,
  },
  row: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    justifyContent: 'space-between' as const,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: c.border,
    minHeight: MIN_TARGET + spacing.sm,
  },
  who: { flex: 1, paddingRight: spacing.sm },
  name: {
    color: c.foreground, fontSize: fontSize.md, fontWeight: fontWeight.semibold,
  },
  meta: { color: c.mutedForeground, fontSize: fontSize.xs, marginTop: 2 },
  actions: { flexDirection: 'row' as const, gap: spacing.xs },
  act: {
    minHeight: MIN_TARGET,
    justifyContent: 'center' as const,
    paddingHorizontal: spacing.md,
    borderRadius: radius.full,
    borderWidth: 1,
  },
  actText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  empty: { padding: spacing.xl, alignItems: 'center' as const },
  emptyTitle: {
    color: c.foreground, fontSize: fontSize.md, fontWeight: fontWeight.semibold,
  },
  emptyBody: {
    color: c.mutedForeground, fontSize: fontSize.sm,
    textAlign: 'center' as const, marginTop: spacing.xs,
  },
  error: { color: c.danger, fontSize: fontSize.sm, marginBottom: spacing.sm },
});
