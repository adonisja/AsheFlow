import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet } from 'react-native';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

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

  const isField = ['walker', 'trainee', 'driver'].includes(data.role);
  const maxDaily = Math.max(1, ...data.daily_last_week.map(d => Math.max(d.delivered, d.rts)));

  const Tile = ({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) => (
    <View style={[s.tile, { backgroundColor: c.background, borderColor: c.border }]}>
      <Text style={[s.tileLabel, { color: c.mutedForeground }]}>{label}</Text>
      <Text style={[s.tileValue, { color: warn ? '#B45309' : c.foreground }]}>{value}</Text>
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

          {/* Last 7 days delivered vs RTS */}
          <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>LAST 7 DAYS</Text>
          <View style={s.barRow}>
            {data.daily_last_week.map(d => (
              <View key={d.day} style={s.barCol}>
                <View style={s.barStack}>
                  {d.rts > 0 && <View style={{ width: '100%', height: `${(d.rts / maxDaily) * 100}%`, backgroundColor: '#F59E0B', borderTopLeftRadius: 2, borderTopRightRadius: 2 }} />}
                  <View style={{ width: '100%', height: `${(d.delivered / maxDaily) * 100}%`, backgroundColor: '#10B981' }} />
                </View>
                <Text style={[s.barLabel, { color: c.mutedForeground }]}>{d.day.slice(5)}</Text>
              </View>
            ))}
          </View>
          <View style={s.legend}>
            <View style={s.legendItem}><View style={[s.dot, { backgroundColor: '#10B981' }]} /><Text style={[s.legendText, { color: c.mutedForeground }]}>Delivered</Text></View>
            <View style={s.legendItem}><View style={[s.dot, { backgroundColor: '#F59E0B' }]} /><Text style={[s.legendText, { color: c.mutedForeground }]}>RTS</Text></View>
          </View>

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
  barRow:      { flexDirection: 'row', alignItems: 'flex-end', height: 90, gap: spacing.xs },
  barCol:      { flex: 1, alignItems: 'center' },
  barStack:    { width: '100%', height: 74, flexDirection: 'column', justifyContent: 'flex-end' },
  barLabel:    { fontSize: 9, marginTop: 2 },
  legend:      { flexDirection: 'row', gap: spacing.md, marginTop: spacing.xs },
  legendItem:  { flexDirection: 'row', alignItems: 'center', gap: 4 },
  dot:         { width: 8, height: 8, borderRadius: 2 },
  legendText:  { fontSize: 10 },
  kvRow:       { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3, gap: spacing.sm },
  kvKey:       { fontSize: fontSize.xs, textTransform: 'capitalize', flex: 1 },
  kvVal:       { fontSize: fontSize.xs },
});
