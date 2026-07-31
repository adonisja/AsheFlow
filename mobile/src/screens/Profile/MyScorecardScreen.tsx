/**
 * My Amazon scorecard — latest week plus trend.
 *
 * This is AMAZON'S assessment of the individual, not AsheFlow's. The distinction
 * matters and is stated on screen: MyPerformanceCard (the "My Stats" tab) is
 * computed from our own DeliveryStop / RTS / rating records, while these figures
 * come from Amazon's weekly scorecard. They are independent sources and can
 * legitimately disagree — that disagreement is exactly what the appeals process
 * exists to contest, so presenting either as "the" number would be wrong.
 *
 * Self-scoped: /scorecards/me/trend filters on employee_id == caller.id and
 * carries no role gate. A driver sees their own row and nobody else's.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, ActivityIndicator } from 'react-native';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { Badge } from '@components/ui/primitives';

type Point = {
  week: string;
  value: number | null;
  raw: string;
  flag: string | null;
};

type MetricTrend = {
  key: string;
  label: string;
  unit: string | null;
  points: Point[];
  latest: number | null;
  previous: number | null;
  delta: number | null;
  direction: string | null;
};

type Trend = {
  weeks: string[];
  standings: { week: string; standing: string | null }[];
  current_standing: string | null;
  metrics: MetricTrend[];
  focus_now: string[];
};

const DASH = '—';

export default function MyScorecardScreen() {
  const c = useColors();
  const s = styles(c);

  const [data, setData] = useState<Trend | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setFailed(false);
    try {
      const res = await apiClient.get('/scorecards/me/trend?weeks=12');
      setData(res.data);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return <ActivityIndicator color={c.primary} style={{ marginVertical: spacing.xl }} />;
  }

  const empty = !data || data.weeks.length === 0;

  return (
    <ScrollView
      contentContainerStyle={s.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => { setRefreshing(true); load(true); }}
          tintColor={c.primary}
        />
      }
    >
      {/* Attribution. Without this the two performance tabs read as contradictory. */}
      <Text style={[s.attribution, { color: c.mutedForeground }]}>
        Amazon's weekly assessment. Your AsheFlow delivery stats are under My Stats —
        the two are measured separately and can differ.
      </Text>

      {failed ? (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={[s.muted, { color: c.mutedForeground }]}>
            Couldn't load your scorecard. Pull down to retry.
          </Text>
        </View>
      ) : empty ? (
        <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={[s.muted, { color: c.mutedForeground }]}>
            No scorecard recorded for you yet. These appear weekly once management
            enters them.
          </Text>
        </View>
      ) : (
        <>
          {/* Standing */}
          <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
            <View style={s.head}>
              <Text style={[s.title, { color: c.foreground }]}>Overall standing</Text>
              <Text style={[s.week, { color: c.mutedForeground }]}>
                {data!.weeks[data!.weeks.length - 1]}
              </Text>
            </View>
            <Text style={[s.standing, { color: c.success }]}>
              {data!.current_standing ?? DASH}
            </Text>

            {/* Standing history, oldest to newest. A gap means no scorecard that
                week — shown, never closed up. */}
            <View style={s.sparkRow}>
              {data!.standings.map(st => (
                <View
                  key={st.week}
                  style={[
                    s.standingBar,
                    { backgroundColor: st.standing ? c.success : c.border },
                  ]}
                />
              ))}
            </View>
          </View>

          {/* What Amazon flagged — the actionable part */}
          {data!.focus_now.length > 0 && (
            <View style={[s.card, { backgroundColor: '#F59E0B14', borderColor: '#F59E0B40' }]}>
              <Text style={[s.title, { color: c.warning, marginBottom: spacing.xs }]}>
                Needs focus this week
              </Text>
              {data!.focus_now.map(label => (
                <Text key={label} style={[s.focusItem, { color: c.foreground }]}>• {label}</Text>
              ))}
            </View>
          )}

          {/* Metric trend */}
          <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
            <Text style={[s.title, { color: c.foreground, marginBottom: spacing.xs }]}>
              Metrics · last {data!.weeks.length} weeks
            </Text>

            {data!.metrics.map(m => {
              const newest = m.points[m.points.length - 1];
              const flagged = newest?.flag === 'needs_focus';
              return (
                <View key={m.key} style={[s.metricRow, { borderTopColor: c.border }]}>
                  <View style={{ flex: 1 }}>
                    <Text style={[s.metricLabel, { color: c.foreground }]} numberOfLines={1}>
                      {m.label}
                    </Text>
                    <Sparkline points={m.points} c={c} />
                  </View>

                  <View style={s.metricRight}>
                    <Text style={[s.metricValue, { color: c.foreground }]}>
                      {newest?.raw || DASH}
                    </Text>
                    {/* Direction is corrected server-side for lower-is-better
                        metrics, so "up" always means improved. Do not re-derive
                        it from delta here. */}
                    {m.direction && m.direction !== 'flat' && (
                      <Text
                        style={[
                          s.metricDelta,
                          { color: m.direction === 'up' ? c.success : c.danger },
                        ]}
                      >
                        {m.direction === 'up' ? '↑' : '↓'} improved
                      </Text>
                    )}
                    {flagged && <Badge tone="warning" size="sm">Needs Focus</Badge>}
                  </View>
                </View>
              );
            })}
          </View>
        </>
      )}
    </ScrollView>
  );
}

/** Bar sparkline. A missing week renders as a faint bar rather than being
 *  interpolated over — absence is information. */
function Sparkline({ points, c }: { points: Point[]; c: ThemeColors }) {
  const vals = points.map(p => p.value).filter((v): v is number => v != null);
  if (vals.length < 2) return null;

  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;

  return (
    <View style={sparkStyles.row}>
      {points.map((p, i) => (
        <View
          key={i}
          style={[
            sparkStyles.bar,
            p.value == null
              ? { height: 14, backgroundColor: c.border }
              : {
                  height: 4 + ((p.value - min) / span) * 14,
                  backgroundColor: p.flag === 'needs_focus' ? c.danger : c.primary,
                },
          ]}
        />
      ))}
    </View>
  );
}

const sparkStyles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'flex-end', gap: 2, marginTop: 4, height: 18 },
  bar: { width: 4, borderRadius: 1 },
});

const styles = (c: ThemeColors) => StyleSheet.create({
  content:      { padding: spacing.lg, paddingBottom: spacing.xxl },
  attribution:  { fontSize: fontSize.xs, lineHeight: 17, marginBottom: spacing.md },
  card:         { borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md },
  head:         { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title:        { fontSize: fontSize.md, fontWeight: fontWeight.bold },
  week:         { fontSize: fontSize.xs },
  standing:     { fontSize: fontSize.xxl, fontWeight: fontWeight.extrabold, marginTop: 2 },
  sparkRow:     { flexDirection: 'row', gap: 3, marginTop: spacing.sm },
  standingBar:  { width: 8, height: 20, borderRadius: 2 },
  focusItem:    { fontSize: fontSize.sm, lineHeight: 20 },
  metricRow:    { flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
                  paddingVertical: spacing.sm, borderTopWidth: StyleSheet.hairlineWidth },
  metricLabel:  { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  metricRight:  { alignItems: 'flex-end', gap: 2 },
  metricValue:  { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  metricDelta:  { fontSize: 10, fontWeight: fontWeight.semibold },
  muted:        { fontSize: fontSize.sm, lineHeight: 20, textAlign: 'center' },
});
