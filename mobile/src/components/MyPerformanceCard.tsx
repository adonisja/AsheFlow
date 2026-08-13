import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet } from 'react-native';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import RecentDaysSection from './RecentDaysSection';

// My Performance card (ADR-203) — the caller's own live delivery/RTS/rating stats
// from OUR data (distinct from the official Amazon Scorecard, ADR-204).
type Perf = {
  role: string;
  lifetime_delivered: number;
  lifetime_rts: number;
  lifetime_missing: number;
  success_pct: number | null;
  avg_stars: number | null;
  grade: string | null;
  trips_today: number;
  trips_this_week: number;
  daily_last_week: { day: string; delivered: number; rts: number }[];
  weekly_trend: { week_start: string; delivered: number }[];
  rts_reasons_30d: { rts_type: string; count: number }[];
  troublesome_addresses_30d: { normalised_address: string; count: number }[];
};

export default function MyPerformanceCard() {
  const c = useColors();
  const s = styles(c);
  const [data, setData] = useState<Perf | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient.get('/field-ops/me/performance')
      .then(r => setData(r.data))
      .catch(() => setData(null))   // silent — a stats card shouldn't error the screen
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <ActivityIndicator color={c.primary} style={{ marginVertical: spacing.md }} />;
  if (!data) return null;

  // Two different questions, so two different gates (ADR-269).
  //
  // isField    — does this person carry a package count of their own?
  //              Captain joins driver here: ADR-256 made captain truck-scoped
  //              and TRUCK_SCOPED_ROLES = ("driver","captain"), so the backend
  //              already returns the whole load for both. Trainer joins too:
  //              they run their own routes when unpaired or partially
  //              supervising, and walker_id (the EXECUTOR, ADR-244) is theirs
  //              on those stops.
  //
  // hasHistory — did they hold a slot on a truck at all? That is everyone
  //              above, and it is what Recent Days needs. Kept as its own
  //              constant so narrowing the tiles later cannot silently take
  //              per-day history away with it.
  const isField = ['walker', 'trainee', 'driver', 'captain', 'trainer'].includes(data.role);
  const hasHistory = isField;

  const Tile = ({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) => (
    <View style={[s.tile, { backgroundColor: c.background, borderColor: c.border }]}>
      <Text style={[s.tileLabel, { color: c.mutedForeground }]}>{label}</Text>
      <Text style={[s.tileValue, { color: warn ? c.warning : c.foreground }]}>{value}</Text>
      {sub ? <Text style={[s.tileSub, { color: c.mutedForeground }]}>{sub}</Text> : null}
    </View>
  );

  return (
    <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
      <Text style={[s.cardTitle, { color: c.foreground }]}>My Performance</Text>
      <Text style={[s.cardHint, { color: c.mutedForeground }]}>Your live stats</Text>

      <View style={s.tileRow}>
        {isField && <Tile label="Delivered" value={data.lifetime_delivered.toLocaleString()} sub="lifetime" />}
        {isField && (
          <Tile label="Success" value={data.success_pct != null ? `${data.success_pct}%` : '—'}
                warn={data.success_pct != null && data.success_pct < 90} />
        )}
        <Tile label="Rating" value={data.avg_stars != null ? `${data.avg_stars}★` : '—'}
              sub={data.grade ? `Grade ${data.grade}` : undefined} />
        {isField && <Tile label="Trips (wk)" value={String(data.trips_this_week)}
              sub={data.trips_today ? `${data.trips_today} today` : undefined} />}
      </View>

      {isField && (
        <>
          <Text style={[s.subLine, { color: c.mutedForeground }]}>
            {data.lifetime_rts.toLocaleString()} RTS · {data.lifetime_missing.toLocaleString()} missing (lifetime)
          </Text>

          {/* The 7-day chart MOVED to RecentDaysSection (below), inside the
              week picker. Here it was a fixed trailing week from a different
              endpoint, so it could not follow the week being viewed and told a
              story disconnected from the cards underneath it. The lifetime
              tiles and the 30-day RTS reason breakdown stay: those are
              genuinely period-independent. */}

          {/* 30-day RTS reasons */}
          {data.rts_reasons_30d.length > 0 && (
            <>
              <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>RTS REASONS (30D)</Text>
              {data.rts_reasons_30d.map(r => (
                <View key={r.rts_type} style={s.kvRow}>
                  <Text style={[s.kvKey, { color: c.foreground }]}>{r.rts_type.replace(/_/g, ' ')}</Text>
                  <Text style={[s.kvVal, { color: c.mutedForeground }]}>{r.count}</Text>
                </View>
              ))}
            </>
          )}

          {/* 30-day troublesome addresses */}
          {data.troublesome_addresses_30d.length > 0 && (
            <>
              <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>TROUBLESOME ADDRESSES (30D)</Text>
              {data.troublesome_addresses_30d.map(a => (
                <View key={a.normalised_address} style={s.kvRow}>
                  <Text style={[s.kvKey, { color: c.foreground }]} numberOfLines={1}>⚠ {a.normalised_address}</Text>
                  <Text style={[s.kvVal, { color: c.mutedForeground }]}>{a.count}</Text>
                </View>
              ))}
            </>
          )}
        </>
      )}

      {/* Per-day detail (ADR-268). Inside this card, not a new screen: the
          tiles above answer "how am I doing overall" from the same source, and
          this answers "what was Thursday" — including the difficulty
          normalisation the aggregates cannot apply. */}
      {hasHistory && <RecentDaysSection />}
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  card:        { borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md },
  cardTitle:   { fontSize: fontSize.md, fontWeight: fontWeight.bold },
  cardHint:    { fontSize: fontSize.xs, marginBottom: spacing.sm },
  tileRow:     { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  tile:        { flexGrow: 1, minWidth: '22%', borderWidth: 1, borderRadius: radius.md, padding: spacing.sm },
  tileLabel:   { fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5 },
  tileValue:   { fontSize: fontSize.lg, fontWeight: fontWeight.bold, marginTop: 2 },
  tileSub:     { fontSize: 10 },
  subLine:     { fontSize: fontSize.xs, marginTop: spacing.sm },
  sectionLabel:{ fontSize: 10, fontWeight: fontWeight.bold, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: spacing.md, marginBottom: spacing.xs },
  legend:      { flexDirection: 'row', gap: spacing.md, marginTop: spacing.xs },
  legendItem:  { flexDirection: 'row', alignItems: 'center', gap: 4 },
  dot:         { width: 8, height: 8, borderRadius: 2 },
  legendText:  { fontSize: 10 },
  kvRow:       { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3, gap: spacing.sm },
  kvKey:       { fontSize: fontSize.xs, textTransform: 'capitalize', flex: 1 },
  kvVal:       { fontSize: fontSize.xs },
});
