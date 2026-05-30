import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, ActivityIndicator, ScrollView,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ── Types ─────────────────────────────────────────────────────────────────────

type Rating = {
  id: string;
  date: string;
  driver_name: string;
  present: boolean;
  stars: number | null;
  comment: string | null;
};

type Profile = {
  walker_name: string;
  total_shifts: number;
  present_shifts: number;
  no_show_count: number;
  avg_stars: number | null;
  presence_rate: number | null;
  grade: string | null;
  ratings: Rating[];
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function gradeColor(grade: string | null): string {
  if (!grade) return '#9CA3AF';
  if (grade === 'A') return '#10B981';
  if (grade === 'B') return '#3B82F6';
  if (grade === 'C') return '#F59E0B';
  if (grade === 'D') return '#F97316';
  return '#EF4444';
}

function Stars({ count }: { count: number | null }) {
  if (count === null) return <Text style={{ color: '#9CA3AF', fontSize: fontSize.sm }}>—</Text>;
  return (
    <Text style={{ fontSize: fontSize.sm }}>
      {'★'.repeat(count)}{'☆'.repeat(5 - count)}
    </Text>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function WalkerPerformanceScreen() {
  const c = useColors();
  const { user } = useAuth();
  const s = styles(c);

  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<Profile | null>(null);

  const load = useCallback(async () => {
    if (!user?.id) return;
    setLoading(true);
    try {
      const res = await apiClient.get(`/field-ops/walker-profile/${user.id}`);
      setProfile(res.data);
    } catch {
      setProfile(null);
    } finally {
      setLoading(false);
    }
  }, [user?.id]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator size="large" color={c.primary} />
      </View>
    );
  }

  if (!profile || profile.total_shifts === 0) {
    return (
      <ScreenShell edges={[]} noHeader title="Performance" subtitle="">
        <View style={s.center}>
          <Text style={{ fontSize: 40 }}>📊</Text>
          <Text style={s.emptyTitle}>No shift history yet</Text>
          <Text style={s.emptySub}>Your performance stats will appear after your first rated shift.</Text>
        </View>
      </ScreenShell>
    );
  }

  const gradeCol = gradeColor(profile.grade);

  return (
    <ScrollView style={s.scroll} contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>

      {/* Grade + headline stats */}
      <View style={[s.heroCard, { backgroundColor: c.surface, borderColor: c.border }]}>
        <View style={[s.gradeBadge, { backgroundColor: gradeCol + '22', borderColor: gradeCol }]}>
          <Text style={[s.gradeText, { color: gradeCol }]}>{profile.grade ?? '—'}</Text>
        </View>
        <View style={{ flex: 1, gap: 6 }}>
          <Text style={[s.walkerName, { color: c.foreground }]}>{profile.walker_name}</Text>
          <View style={s.statsRow}>
            <MiniStat label="Shifts"    value={profile.total_shifts}               c={c} />
            <MiniStat label="Presence"  value={`${profile.presence_rate ?? 0}%`}   c={c} />
            <MiniStat label="No-shows"  value={profile.no_show_count}              c={c} />
          </View>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <Stars count={profile.avg_stars !== null ? Math.round(profile.avg_stars) : null} />
            {profile.avg_stars !== null && (
              <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>
                avg {profile.avg_stars.toFixed(1)} / 5
              </Text>
            )}
          </View>
        </View>
      </View>

      {/* Recent ratings */}
      <Text style={[s.sectionTitle, { color: c.foreground }]}>Recent Shifts</Text>
      {profile.ratings.slice(0, 30).map(r => (
        <View key={r.id} style={[s.ratingCard, { backgroundColor: c.surface, borderColor: c.border, borderLeftColor: r.present ? c.primary : '#EF4444' }]}>
          <View style={s.ratingHeader}>
            <Text style={[s.ratingDate, { color: c.foreground }]}>{r.date}</Text>
            <View style={[s.presentBadge, {
              backgroundColor: r.present ? '#10B98122' : '#EF444422',
              borderColor:     r.present ? '#10B981'   : '#EF4444',
            }]}>
              <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: r.present ? '#10B981' : '#EF4444' }}>
                {r.present ? 'Present' : 'No-show'}
              </Text>
            </View>
          </View>
          <Text style={[s.driverName, { color: c.mutedForeground }]}>Driver: {r.driver_name}</Text>
          {r.present && <Stars count={r.stars} />}
          {r.comment && (
            <Text style={[s.comment, { color: c.mutedForeground }]}>"{r.comment}"</Text>
          )}
        </View>
      ))}

      <View style={{ height: spacing.xl }} />
    </ScrollView>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MiniStat({ label, value, c }: { label: string; value: string | number; c: any }) {
  return (
    <View style={{ alignItems: 'center' }}>
      <Text style={{ fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground }}>{value}</Text>
      <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>{label}</Text>
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  scroll:        { flex: 1, backgroundColor: c.background },
  center:        { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: c.background },
  emptyTitle:    { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, marginTop: spacing.sm },
  emptySub:      { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center', paddingHorizontal: spacing.xl },
  sectionTitle:  { fontSize: fontSize.base, fontWeight: fontWeight.semibold },

  heroCard:      { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, flexDirection: 'row', gap: spacing.md, alignItems: 'flex-start' },
  gradeBadge:    { width: 64, height: 64, borderRadius: radius.md, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  gradeText:     { fontSize: 32, fontWeight: fontWeight.bold },
  walkerName:    { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
  statsRow:      { flexDirection: 'row', gap: spacing.lg },

  ratingCard:    { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.xs, borderLeftWidth: 4, gap: spacing.xs },
  ratingHeader:  { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  ratingDate:    { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  presentBadge:  { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  driverName:    { fontSize: fontSize.xs },
  comment:       { fontSize: fontSize.xs, fontStyle: 'italic', marginTop: 2 },
});
