import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// Backend /mine/summary returns: { total_marks, distinct_trainees_with_marks, underperforming }
type Summary = {
  total_marks: number;
  distinct_trainees_with_marks: number;
  underperforming: boolean;
};

// Backend /mine returns: { id, trainee: {id, name}, phase, record_date, reason,
//                           debt_originated, debt_chain_context, created_at }
type Mark = {
  id: string;
  trainee_name: string;
  record_date: string | null;
  created_at: string;
  reason: string;
  debt_chain_context?: string;
};

export default function TrainerPerformanceScreen() {
  const c = useColors();

  const [summary,    setSummary]    = useState<Summary | null>(null);
  const [marks,      setMarks]      = useState<Mark[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded,   setExpanded]   = useState<Set<string>>(new Set());

  const fetch = useCallback(async () => {
    try {
      const [sumRes, marksRes] = await Promise.all([
        apiClient.get('/trainer-marks/mine/summary'),
        apiClient.get('/trainer-marks/mine'),
      ]);
      setSummary(sumRes.data);
      setMarks((marksRes.data ?? []).map((m: any) => ({
        id:                m.id,
        trainee_name:      m.trainee?.name ?? 'Unknown',
        record_date:       m.record_date ?? null,
        created_at:        m.created_at,
        reason:            m.reason ?? '',
        debt_chain_context: m.debt_chain_context ?? undefined,
      })));
    } catch {
      setSummary(null);
      setMarks([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  const toggle = (id: string) =>
    setExpanded(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const standingColor = (underperforming: boolean, total: number) => {
    if (!underperforming && total === 0) return c.success;
    if (!underperforming) return c.warning;
    return c.danger;
  };

  const standingLabel = (underperforming: boolean, total: number) => {
    if (!underperforming && total === 0) return 'GOOD';
    if (!underperforming) return 'WATCH';
    return 'REVIEW';
  };

  const st = styles(c);

  return (
    <ScreenShell
      noHeader
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => { setRefreshing(true); fetch(); }}
    >
      {/* Standing banner */}
      {summary && (
        <View style={[st.banner, { backgroundColor: standingColor(summary.underperforming, summary.total_marks) + '18', borderColor: standingColor(summary.underperforming, summary.total_marks) + '40' }]}>
          <Text style={[st.standingLabel, { color: standingColor(summary.underperforming, summary.total_marks) }]}>
            Standing: {standingLabel(summary.underperforming, summary.total_marks)}
          </Text>
          {summary.underperforming && (
            <Text style={[st.standingHint, { color: c.danger }]}>
              You have been flagged across multiple trainees. Management has been notified.
            </Text>
          )}
        </View>
      )}

      {/* KPI row */}
      {summary && (
        <View style={st.kpiRow}>
          <KpiCard label="Total Marks" value={String(summary.total_marks)} color={summary.total_marks > 0 ? c.danger : c.success} c={c} />
          <KpiCard label="Trainees Affected" value={String(summary.distinct_trainees_with_marks)} color={c.foreground} c={c} />
        </View>
      )}

      {/* Mark history */}
      <Text style={st.sectionTitle}>Mark History</Text>
      {marks.length === 0 ? (
        <View style={st.emptyCard}>
          <Text style={st.emptyText}>No marks on record</Text>
        </View>
      ) : marks.map(m => (
        <TouchableOpacity key={m.id} style={st.markCard} onPress={() => toggle(m.id)} activeOpacity={0.8}>
          <View style={st.markHeader}>
            <View style={[st.severityDot, { backgroundColor: c.danger }]} />
            <View style={{ flex: 1 }}>
              <Text style={st.markContext}>{m.reason}</Text>
              <Text style={st.markMeta}>{m.trainee_name} · {(m.record_date ?? m.created_at.split('T')[0])}</Text>
            </View>
            <Text style={st.chevron}>{expanded.has(m.id) ? '▲' : '▼'}</Text>
          </View>
          {expanded.has(m.id) && m.debt_chain_context && (
            <View style={st.markDetail}>
              <Text style={st.markDetailText}>{m.debt_chain_context}</Text>
            </View>
          )}
        </TouchableOpacity>
      ))}
    </ScreenShell>
  );
}

function KpiCard({ label, value, color, c }: { label: string; value: string; color: string; c: ThemeColors }) {
  const s = StyleSheet.create({
    card:  { flex: 1, backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, alignItems: 'center', margin: spacing.xs },
    val:   { fontSize: fontSize.xxl, fontWeight: fontWeight.extrabold, color },
    lbl:   { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 4, textTransform: 'uppercase', letterSpacing: 0.6 },
  });
  return <View style={s.card}><Text style={s.val}>{value}</Text><Text style={s.lbl}>{label}</Text></View>;
}

const styles = (c: ThemeColors) => StyleSheet.create({
  banner:       { borderRadius: radius.lg, borderWidth: 1, padding: spacing.md, marginBottom: spacing.md },
  standingLabel:{ fontSize: fontSize.md, fontWeight: fontWeight.bold },
  standingHint: { fontSize: fontSize.sm, marginTop: spacing.xs, lineHeight: 20 },
  kpiRow:       { flexDirection: 'row', marginHorizontal: -spacing.xs, marginBottom: spacing.md },
  sectionTitle: { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, marginBottom: spacing.sm },
  markCard:     { backgroundColor: c.card, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.sm },
  markHeader:   { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  severityDot:  { width: 8, height: 8, borderRadius: 4 },
  markContext:  { fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.foreground },
  markMeta:     { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  chevron:      { fontSize: fontSize.xs, color: c.mutedForeground },
  markDetail:   { marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.border },
  markDetailText:{ fontSize: fontSize.sm, color: c.foreground, lineHeight: 20 },
  emptyCard:    { backgroundColor: c.surfaceMuted, borderRadius: radius.lg, padding: spacing.xl, alignItems: 'center' },
  emptyText:    { fontSize: fontSize.base, color: c.mutedForeground },
});
