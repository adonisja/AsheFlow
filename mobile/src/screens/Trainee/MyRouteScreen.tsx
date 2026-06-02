import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, ScrollView, RefreshControl,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ── Types ─────────────────────────────────────────────────────────────────────

type TripStatus = 'pending' | 'in_progress' | 'completed';

type WalkerTrip = {
  id: string;
  trip_number: number;
  bag_ids: string[];
  tba_numbers: string[];
  tag_numbers: string[];
  status: TripStatus;
  departed_at: string | null;
  returned_at: string | null;
};

type WalkerRoute = {
  id: string;
  total_packages: number;
  total_bags: number;
  planned_trips: number;
  trips: WalkerTrip[];
};

// ── Status badge ──────────────────────────────────────────────────────────────

function statusColor(status: TripStatus, primary: string): string {
  if (status === 'completed')  return '#10B981';
  if (status === 'in_progress') return primary;
  return '#9CA3AF';
}

function statusLabel(status: TripStatus): string {
  if (status === 'completed')  return 'Completed';
  if (status === 'in_progress') return 'In Progress';
  return 'Pending';
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// ── Main component ────────────────────────────────────────────────────────────

export default function MyRouteScreen() {
  const c = useColors();
  const { user } = useAuth();
  const { fetchId } = useEmployeeId();
  const s = styles(c);

  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [route,      setRoute]      = useState<WalkerRoute | null>(null);
  const [updating,   setUpdating]   = useState<string | null>(null); // trip id being updated

  const load = useCallback(async (opts?: { refresh?: boolean }) => {
    const eid = await fetchId();
    if (!eid) return;
    if (opts?.refresh) setRefreshing(true); else setLoading(true);
    try {
      // Find today's truck assignment for the current user
      const dispRes = await apiClient.get(`/dispatch/${today()}`);
      const myMember = dispRes.data?.assignment_members?.find(
        (m: any) => m.employee_id === eid
      );
      if (!myMember) { setRoute(null); return; }

      const assignmentId = myMember.truck_assignment_id;
      const routesRes = await apiClient.get(`/walker-routes/assignment/${assignmentId}`);
      const routes: WalkerRoute[] = routesRes.data ?? [];

      // Walker is matched to a route by walker_id
      const myRoute = routes.find((r: any) => r.walker_id === eid) ?? null;
      setRoute(myRoute);
    } catch {
      setRoute(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [fetchId]);

  useEffect(() => { load(); }, [load]);

  async function advanceTrip(trip: WalkerTrip) {
    const nextStatus: TripStatus =
      trip.status === 'pending' ? 'in_progress' :
      trip.status === 'in_progress' ? 'completed' : 'completed';

    const label = trip.status === 'pending' ? 'Start Trip' : 'Return / Complete';
    const message = trip.status === 'pending'
      ? `Mark Trip ${trip.trip_number} as started?`
      : `Mark Trip ${trip.trip_number} as completed?`;

    Alert.alert(label, message, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: label,
        onPress: async () => {
          setUpdating(trip.id);
          try {
            await apiClient.patch(`/walker-routes/trips/${trip.id}/status`, { status: nextStatus });
            setRoute(prev => {
              if (!prev) return prev;
              return {
                ...prev,
                trips: prev.trips.map(t =>
                  t.id === trip.id ? { ...t, status: nextStatus } : t
                ),
              };
            });
          } catch {
            Alert.alert('Error', 'Could not update trip status. Try again.');
          } finally {
            setUpdating(null);
          }
        },
      },
    ]);
  }

  // ── Render ──

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator size="large" color={c.primary} />
      </View>
    );
  }

  if (!route) {
    return (
      <ScreenShell edges={[]} noHeader title="My Route" subtitle="">
        <View style={s.center}>
          <Text style={{ fontSize: 40 }}>🗺️</Text>
          <Text style={s.emptyTitle}>No route assigned yet</Text>
          <Text style={s.emptySub}>
            Your trainer will commit the route sort before routes appear here.
          </Text>
          <TouchableOpacity onPress={() => load()} style={[s.refreshBtn, { borderColor: c.primary }]}>
            <Text style={{ color: c.primary, fontSize: fontSize.sm, fontWeight: fontWeight.medium }}>Refresh</Text>
          </TouchableOpacity>
        </View>
      </ScreenShell>
    );
  }

  const completedTrips = route.trips.filter(t => t.status === 'completed').length;

  return (
    <ScrollView
      style={s.scroll}
      contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={() => load({ refresh: true })} tintColor={c.primary} />
      }
    >

      {/* Summary card */}
      <View style={[s.summaryCard, { borderColor: c.border, backgroundColor: c.surface }]}>
        <View style={s.summaryRow}>
          <StatPill label="Packages" value={route.total_packages} c={c} />
          <StatPill label="Bags"     value={route.total_bags}     c={c} />
          <StatPill label="Trips"    value={route.planned_trips}  c={c} />
        </View>
        <View style={[s.progressBar, { backgroundColor: c.border }]}>
          <View style={[s.progressFill, {
            backgroundColor: c.primary,
            width: `${route.planned_trips > 0 ? (completedTrips / route.planned_trips) * 100 : 0}%` as any,
          }]} />
        </View>
        <Text style={[s.progressLabel, { color: c.mutedForeground }]}>
          {completedTrips} / {route.planned_trips} trips completed
        </Text>
      </View>

      {/* Trips */}
      <Text style={[s.sectionTitle, { color: c.foreground }]}>Trips</Text>
      {route.trips.map(trip => {
        const color = statusColor(trip.status, c.primary);
        const canAdvance = trip.status !== 'completed';
        const isUpdating = updating === trip.id;

        return (
          <View key={trip.id} style={[s.tripCard, { borderColor: c.border, backgroundColor: c.surface, borderLeftColor: color }]}>
            <View style={s.tripHeader}>
              <Text style={[s.tripNumber, { color: c.foreground }]}>Trip {trip.trip_number}</Text>
              <View style={[s.badge, { backgroundColor: color + '22', borderColor: color }]}>
                <Text style={[s.badgeText, { color }]}>{statusLabel(trip.status)}</Text>
              </View>
            </View>

            <Text style={[s.tripDetail, { color: c.mutedForeground }]}>
              Bags: {trip.bag_ids.join(', ')}
            </Text>
            {trip.tba_numbers.length > 0 && (
              <Text style={[s.tripDetail, { color: c.mutedForeground }]} numberOfLines={2}>
                TBAs: {trip.tba_numbers.slice(0, 4).join(', ')}{trip.tba_numbers.length > 4 ? ` +${trip.tba_numbers.length - 4} more` : ''}
              </Text>
            )}

            {trip.departed_at && (
              <Text style={[s.timeText, { color: c.mutedForeground }]}>
                Departed: {new Date(trip.departed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </Text>
            )}
            {trip.returned_at && (
              <Text style={[s.timeText, { color: c.mutedForeground }]}>
                Returned: {new Date(trip.returned_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </Text>
            )}

            {canAdvance && (
              <TouchableOpacity
                style={[s.actionBtn, { backgroundColor: color, opacity: isUpdating ? 0.6 : 1 }]}
                onPress={() => advanceTrip(trip)}
                disabled={isUpdating}
                activeOpacity={0.8}
              >
                {isUpdating
                  ? <ActivityIndicator size="small" color="#fff" />
                  : <Text style={s.actionBtnText}>
                      {trip.status === 'pending' ? 'Start Trip' : 'Return / Complete'}
                    </Text>
                }
              </TouchableOpacity>
            )}
          </View>
        );
      })}

      <View style={{ height: spacing.xl }} />
    </ScrollView>
  );
}

// ── Stat pill ─────────────────────────────────────────────────────────────────

function StatPill({ label, value, c }: { label: string; value: number; c: any }) {
  return (
    <View style={{ alignItems: 'center', flex: 1 }}>
      <Text style={{ fontSize: fontSize.xl, fontWeight: fontWeight.bold, color: c.foreground }}>{value}</Text>
      <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>{label}</Text>
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  scroll:       { flex: 1, backgroundColor: c.background },
  center:       { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: c.background },
  emptyTitle:   { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, marginTop: spacing.sm },
  emptySub:     { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center', paddingHorizontal: spacing.xl },
  refreshBtn:   { marginTop: spacing.md, borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  sectionTitle: { fontSize: fontSize.base, fontWeight: fontWeight.semibold },

  summaryCard:  { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: spacing.sm },
  summaryRow:   { flexDirection: 'row', justifyContent: 'space-around' },
  progressBar:  { height: 6, borderRadius: 3, overflow: 'hidden' },
  progressFill: { height: 6, borderRadius: 3 },
  progressLabel:{ fontSize: fontSize.xs, textAlign: 'center' },

  tripCard:     { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm, borderLeftWidth: 4, gap: spacing.xs },
  tripHeader:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  tripNumber:   { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
  tripDetail:   { fontSize: fontSize.sm },
  timeText:     { fontSize: fontSize.xs },
  badge:        { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  badgeText:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  actionBtn:    { borderRadius: radius.sm, padding: spacing.sm, alignItems: 'center', marginTop: spacing.xs },
  actionBtnText:{ color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
});
