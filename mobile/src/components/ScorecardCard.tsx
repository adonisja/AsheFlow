import React, { useEffect, useState } from 'react';
import { View, Text, ActivityIndicator, StyleSheet } from 'react-native';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// Official Amazon (NYCD) weekly scorecard (ADR-204), read-only on My Account.
type Metric = { id: string; label: string; value: string; unit?: string | null; flag?: string | null };
type Scorecard = { id: string; week: string; overall_standing?: string | null; metrics: Metric[] };

export default function ScorecardCard() {
  const c = useColors();
  const s = styles(c);
  const [sc, setSc] = useState<Scorecard | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient.get('/scorecards/me')
      .then(r => setSc((r.data ?? [])[0] ?? null))   // latest week
      .catch(() => setSc(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <ActivityIndicator color={c.primary} style={{ marginVertical: spacing.md }} />;
  if (!sc) return null;

  return (
    <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
      <View style={s.head}>
        <Text style={[s.title, { color: c.foreground }]}>Amazon Scorecard</Text>
        <Text style={[s.week, { color: c.mutedForeground }]}>{sc.week}</Text>
      </View>

      {sc.overall_standing ? (
        <View style={[s.overall, { backgroundColor: '#10B98118', borderColor: '#10B98140' }]}>
          <Text style={[s.overallLabel, { color: c.mutedForeground }]}>OVERALL STANDING</Text>
          <Text style={s.overallValue}>{sc.overall_standing}</Text>
        </View>
      ) : null}

      {sc.metrics.map(m => (
        <View key={m.id} style={[s.row, { borderTopColor: c.border }]}>
          <Text style={[s.rowLabel, { color: c.foreground }]} numberOfLines={1}>{m.label}</Text>
          <Text style={[s.rowValue, { color: c.foreground }]}>
            {m.value}{m.unit && !m.value.includes(m.unit) ? ` ${m.unit}` : ''}
          </Text>
          {m.flag ? (
            <View style={[s.flag, { backgroundColor: (m.flag === 'excellent' ? '#10B981' : '#F59E0B') + '22' }]}>
              <Text style={[s.flagText, { color: m.flag === 'excellent' ? '#047857' : '#B45309' }]}>
                {m.flag === 'excellent' ? 'Excellent' : 'Needs Focus'}
              </Text>
            </View>
          ) : null}
        </View>
      ))}
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  card:         { borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md },
  head:         { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.sm },
  title:        { fontSize: fontSize.md, fontWeight: fontWeight.bold },
  week:         { fontSize: fontSize.xs },
  overall:      { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.sm },
  overallLabel: { fontSize: 10, fontWeight: fontWeight.bold, letterSpacing: 0.5 },
  overallValue: { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: '#047857' },
  row:          { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xs + 2, borderTopWidth: StyleSheet.hairlineWidth },
  rowLabel:     { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, flex: 1 },
  rowValue:     { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  flag:         { paddingHorizontal: spacing.xs + 2, paddingVertical: 1, borderRadius: radius.sm },
  flagText:     { fontSize: 10, fontWeight: fontWeight.semibold },
});
