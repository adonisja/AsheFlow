import React, { useEffect, useState, useCallback } from 'react';
import { errorText } from '@api/errorText';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, ScrollView, RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useTabParams } from '@navigation/index';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import PageHeader from '@components/ui/PageHeader';
import { ReportsToSign, StateLine, StolenPackageForm, StolenPackageReportView, type State } from './StolenPackageReport';

type Incident = {
  id: string;
  category: string;
  severity: string;
  description: string;
  resolved: boolean;
  date: string;          // the local day it happened (ADR-521)
  created_at: string;
  // ADR-512: on a stolen-package incident with a report
  stolen_report_state?: State | null;
  my_report_version?: 'da' | 'reviewer' | null;
};

const CATEGORIES = [
  'vehicle', 'injury', 'stolen_packages', 'customer_complaint',
  'route_issue', 'crew_conduct', 'safety_hazard', 'other',
] as const;

const CATEGORY_LABELS: Record<string, string> = {
  vehicle: 'Vehicle', injury: 'Injury', stolen_packages: 'Stolen Packages',
  customer_complaint: 'Customer Complaint', route_issue: 'Route Issue',
  crew_conduct: 'Crew Conduct', safety_hazard: 'Safety Hazard', other: 'Other',
};

const AUTO_SEVERITY: Record<string, string> = {
  injury: 'critical', vehicle: 'warning', stolen_packages: 'warning',
  safety_hazard: 'warning', customer_complaint: 'info',
  route_issue: 'info', crew_conduct: 'info', other: 'info',
};

const SEVERITY_COLOR: Record<string, (c: ThemeColors) => string> = {
  critical: c => c.danger,
  warning:  c => c.warning,
  info:     c => c.info,
};

export default function IncidentsScreen() {
  const c = useColors();
  const { user } = useAuth();

  const [tab, setTab] = useState<'report' | 'history'>('report');

  // Form state
  const [category,    setCategory]    = useState<string>('vehicle');
  const [description, setDescription] = useState('');
  const [submitting,  setSubmitting]  = useState(false);
  // Injury extras
  const [bodyPart,    setBodyPart]    = useState('');
  const [medAttn,     setMedAttn]     = useState<boolean | null>(null);
  // ADR-512: refreshes the "to sign" list and history after a report is filed or signed
  const [reportKey,   setReportKey]   = useState(0);

  // History state
  const [incidents,   setIncidents]   = useState<Incident[]>([]);
  const [loading,     setLoading]     = useState(false);
  const [refreshing,  setRefreshing]  = useState(false);
  const [expanded,    setExpanded]    = useState<Set<string>>(new Set());
  const [historyCat,  setHistoryCat]  = useState<string>('');
  // ADR-519: a notification opens this tab at its incident.
  const linked = useTabParams('Incidents');
  const linkedId = linked?.params.id ?? null;
  useEffect(() => {
    if (!linkedId) return;
    setTab('history');
    setHistoryCat('');
    setExpanded(new Set([linkedId]));
  }, [linkedId, linked?.nonce]);

  const fetchHistory = useCallback(async (opts?: { refresh?: boolean }) => {
    if (opts?.refresh) setRefreshing(true); else setLoading(true);
    try {
      // Filtered on the server: the list is paginated.
      const res = await apiClient.get('/incidents/my', { params: historyCat ? { category: historyCat } : {} });
      setIncidents(res.data ?? []);
    } catch {
      setIncidents([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [historyCat]);

  useEffect(() => { if (tab === 'history') fetchHistory(); }, [tab, fetchHistory, reportKey]);

  const submitIncident = useCallback(async () => {
    if (!description.trim()) { Alert.alert('Required', 'Please enter a description.'); return; }
    setSubmitting(true);
    try {
      // Field names must match IncidentCreate exactly — the old payload
      // omitted the required `date` and used unknown keys (body_part,
      // tba_count, location), so every submit 422'd.
      const now = new Date();
      const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
      const payload: Record<string, any> = {
        date: todayStr,
        category,
        severity: AUTO_SEVERITY[category] ?? 'info',
        description,
      };
      if (category === 'injury') {
        payload.body_part_affected = bodyPart || undefined;
        payload.medical_attention_required = medAttn;
      }
      await apiClient.post('/incidents/', payload);
      Alert.alert('Submitted', 'Incident report filed. Management has been notified.');
      setDescription(''); setBodyPart(''); setMedAttn(null);
      setCategory('vehicle');
    } catch (err: unknown) {
      Alert.alert('Error', errorText(err, 'Could not submit. Try again.'));
    } finally {
      setSubmitting(false);
    }
  }, [category, description, bodyPart, medAttn]);

  const toggle = (id: string) =>
    setExpanded(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const s = styles(c);

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <PageHeader title="Incidents" subtitle="Report and track incidents" />
      {/* Tab bar */}
      <View style={s.tabBar}>
        {(['report', 'history'] as const).map(t => (
          <TouchableOpacity key={t} style={[s.tab, tab === t && s.tabActive]} onPress={() => setTab(t)}>
            <Text style={[s.tabText, tab === t && s.tabTextActive]}>
              {t === 'report' ? 'Report Incident' : 'My History'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        keyboardShouldPersistTaps="handled"
        automaticallyAdjustKeyboardInsets
        refreshControl={
          tab === 'history'
            ? <RefreshControl refreshing={refreshing} onRefresh={() => fetchHistory({ refresh: true })} tintColor={c.primary} />
            : undefined
        }
      >
        {tab === 'report' ? (
          <>
            <ReportsToSign refreshKey={reportKey} onSigned={() => setReportKey(k => k + 1)} />
            <Text style={s.pageTitle}>Report Incident</Text>
            <Text style={s.subtitle}>{new Date().toLocaleDateString()}</Text>

            {/* Category */}
            <Text style={s.label}>Category</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: spacing.md }}>
              {CATEGORIES.map(cat => (
                <TouchableOpacity
                  key={cat}
                  style={[s.chip, category === cat && { backgroundColor: c.primary, borderColor: c.primary }]}
                  onPress={() => setCategory(cat)}
                >
                  <Text style={[s.chipText, category === cat && { color: c.primaryForeground }]}>{CATEGORY_LABELS[cat]}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>

            {/* Auto severity badge */}
            <View style={[s.severityBadge, { backgroundColor: SEVERITY_COLOR[AUTO_SEVERITY[category] ?? 'info'](c) + '18' }]}>
              <Text style={[s.severityText, { color: SEVERITY_COLOR[AUTO_SEVERITY[category] ?? 'info'](c) }]}>
                Severity: {(AUTO_SEVERITY[category] ?? 'info').toUpperCase()}
              </Text>
            </View>

            {/* Injury extras */}
            {category === 'injury' && (
              <>
                <Text style={s.label}>Body Part Affected</Text>
                <TextInput
                  style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }]}
                  value={bodyPart}
                  onChangeText={setBodyPart}
                  placeholder="e.g. left hand"
                  placeholderTextColor={c.placeholder}
                />
                <Text style={s.label}>Medical Attention Required?</Text>
                <View style={s.boolRow}>
                  {[true, false].map(val => (
                    <TouchableOpacity
                      key={String(val)}
                      style={[s.boolBtn, medAttn === val && { backgroundColor: c.primary, borderColor: c.primary }]}
                      onPress={() => setMedAttn(val)}
                    >
                      <Text style={[s.boolText, medAttn === val && { color: c.primaryForeground }]}>{val ? 'Yes' : 'No'}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </>
            )}

            {/* ADR-512: the DSP's stolen-package report replaces the generic form. */}
            {category === 'stolen_packages' && (
              <StolenPackageForm mode="file" onDone={msg => {
                Alert.alert('Filed', msg);
                setCategory('vehicle'); setReportKey(k => k + 1);
              }} />
            )}

            {category !== 'stolen_packages' && (<>
            {/* Description */}
            <Text style={s.label}>Description *</Text>
            <TextInput
              style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }]}
              value={description}
              onChangeText={setDescription}
              placeholder="Describe what happened…"
              placeholderTextColor={c.placeholder}
              multiline
              numberOfLines={5}
              textAlignVertical="top"
            />

            <TouchableOpacity
              style={[s.btn, { backgroundColor: c.danger, opacity: submitting ? 0.6 : 1 }]}
              onPress={submitIncident}
              disabled={submitting}
            >
              {submitting ? <ActivityIndicator color={c.primaryForeground} /> : <Text style={s.btnText}>Submit Report</Text>}
            </TouchableOpacity>
            </>)}
          </>
        ) : (
          <>
            <Text style={s.pageTitle}>My Incidents</Text>
            {!!linkedId && !loading && incidents.length > 0 && !incidents.some(i => i.id === linkedId) && (
              <Text style={s.incMeta}>This item is no longer available.</Text>
            )}
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginVertical: spacing.sm }}
              accessibilityLabel="Filter by category">
              {['', ...CATEGORIES].map(cat => (
                <TouchableOpacity
                  key={cat || 'all'}
                  accessibilityRole="radio" accessibilityState={{ checked: historyCat === cat }}
                  style={[s.chip, historyCat === cat && { backgroundColor: c.primary, borderColor: c.primary }]}
                  onPress={() => setHistoryCat(cat)}
                >
                  <Text style={[s.chipText, historyCat === cat && { color: c.primaryForeground }]}>{cat ? CATEGORY_LABELS[cat] : 'All'}</Text>
                </TouchableOpacity>
              ))}
            </ScrollView>
            {(historyCat === 'stolen_packages' || incidents.some(i => i.category === 'stolen_packages')) && (
              <Text style={s.incMeta}>Accepted stolen-package reports stay here for 7 days.</Text>
            )}
            {loading ? (
              <ActivityIndicator color={c.primary} style={{ marginTop: spacing.xl }} />
            ) : incidents.length === 0 ? (
              <View style={s.emptyCard}><Text style={s.emptyText}>{historyCat ? 'No incidents in this category' : 'No incidents yet'}</Text></View>
            ) : incidents.map(inc => (
              <TouchableOpacity key={inc.id} style={s.incCard} onPress={() => toggle(inc.id)} activeOpacity={0.8}>
                <View style={s.incHeader}>
                  <View style={[s.sevDot, { backgroundColor: SEVERITY_COLOR[inc.severity]?.(c) ?? c.mutedForeground }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.incCategory}>{CATEGORY_LABELS[inc.category] ?? inc.category}</Text>
                    <Text style={s.incMeta}>
                      {inc.date}{inc.my_report_version === 'reviewer' ? ' · Verified by you' : ''}
                    </Text>
                    {inc.stolen_report_state && (
                      <StateLine state={inc.stolen_report_state} verifier={inc.my_report_version === 'reviewer' ? 'you' : null} />
                    )}
                  </View>
                  {/* The API returns `resolved`, never `status`: this badge read a
                      field that does not exist and was always blank (found ADR-512). */}
                  {!inc.stolen_report_state && (
                    <View style={[s.statusBadge, { backgroundColor: inc.resolved ? c.success + '22' : c.warning + '22' }]}>
                      <Text style={[s.statusText, { color: inc.resolved ? c.success : c.warning }]}>
                        {inc.resolved ? 'resolved' : 'open'}
                      </Text>
                    </View>
                  )}
                  <Text style={s.chevron}>{expanded.has(inc.id) ? '▲' : '▼'}</Text>
                </View>
                {expanded.has(inc.id) && (
                  <View style={s.incDetail}>
                    {inc.category === 'stolen_packages'
                      ? <StolenPackageReportView key={reportKey} incidentId={inc.id} />
                      : <Text style={s.incDesc}>{inc.description}</Text>}
                  </View>
                )}
              </TouchableOpacity>
            ))}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:          { flex: 1, backgroundColor: c.background },
  tabBar:        { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: c.border, backgroundColor: c.surface },
  tab:           { flex: 1, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  tabActive:     { borderBottomWidth: 2, borderBottomColor: c.primary },
  tabText:       { fontSize: fontSize.sm, color: c.mutedForeground, fontWeight: fontWeight.medium },
  tabTextActive: { color: c.primary, fontWeight: fontWeight.semibold },
  scroll:        { flex: 1 },
  content:       { padding: spacing.lg, paddingBottom: 80 },
  pageTitle:     { fontSize: fontSize.xxl, fontWeight: fontWeight.extrabold, color: c.foreground },
  subtitle:      { fontSize: fontSize.sm, color: c.mutedForeground, marginTop: 2, marginBottom: spacing.lg },
  label:         { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.foreground, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: spacing.xs, marginTop: spacing.sm },
  chip:          { paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, borderRadius: radius.full, borderWidth: 1, borderColor: c.border, marginRight: spacing.xs, backgroundColor: c.card },
  chipText:      { fontSize: fontSize.xs, color: c.foreground },
  severityBadge: { borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.sm, alignSelf: 'flex-start' },
  severityText:  { fontSize: fontSize.xs, fontWeight: fontWeight.bold, textTransform: 'uppercase', letterSpacing: 0.8 },
  input:         { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, fontSize: fontSize.sm, marginBottom: spacing.sm },
  boolRow:       { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.sm },
  boolBtn:       { flex: 1, borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center', backgroundColor: c.card },
  boolText:      { fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.foreground },
  textArea:      { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, fontSize: fontSize.sm, minHeight: 110, marginBottom: spacing.md },
  btn:           { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', marginBottom: spacing.lg },
  btnText:       { color: c.primaryForeground, fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  incCard:       { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.sm },
  incHeader:     { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  sevDot:        { width: 8, height: 8, borderRadius: 4 },
  incCategory:   { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground },
  incMeta:       { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  statusBadge:   { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  statusText:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  chevron:       { fontSize: fontSize.xs, color: c.mutedForeground },
  incDetail:     { marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.border },
  incDesc:       { fontSize: fontSize.sm, color: c.foreground, lineHeight: 20 },
  emptyCard:     { backgroundColor: c.surfaceMuted, borderRadius: radius.lg, padding: spacing.xl, alignItems: 'center', marginTop: spacing.xl },
  emptyText:     { fontSize: fontSize.base, color: c.mutedForeground },
});
