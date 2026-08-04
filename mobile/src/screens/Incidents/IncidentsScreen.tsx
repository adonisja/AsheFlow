import React, { useEffect, useState, useCallback } from 'react';
import { errorText } from '@api/errorText';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, ScrollView, RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import PageHeader from '@components/ui/PageHeader';

type Incident = {
  id: string;
  category: string;
  severity: string;
  description: string;
  status: string;
  created_at: string;
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
  // Stolen packages extras
  const [tbaCount,    setTbaCount]    = useState('');
  const [location,    setLocation]    = useState('');
  const [witness,     setWitness]     = useState('');
  const [stolenTime,  setStolenTime]  = useState('');

  // History state
  const [incidents,   setIncidents]   = useState<Incident[]>([]);
  const [loading,     setLoading]     = useState(false);
  const [refreshing,  setRefreshing]  = useState(false);
  const [expanded,    setExpanded]    = useState<Set<string>>(new Set());

  const fetchHistory = useCallback(async (opts?: { refresh?: boolean }) => {
    if (opts?.refresh) setRefreshing(true); else setLoading(true);
    try {
      const res = await apiClient.get('/incidents/my');
      setIncidents(res.data ?? []);
    } catch {
      setIncidents([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { if (tab === 'history') fetchHistory(); }, [tab, fetchHistory]);

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
      if (category === 'stolen_packages') {
        payload.packages_tba = tbaCount ? Number(tbaCount) : undefined;
        payload.incident_location = location || undefined;
        payload.witness_name = witness || undefined;
        payload.incident_time = stolenTime || undefined;
      }
      await apiClient.post('/incidents/', payload);
      Alert.alert('Submitted', 'Incident report filed. Management has been notified.');
      setDescription(''); setBodyPart(''); setMedAttn(null);
      setTbaCount(''); setLocation(''); setWitness(''); setStolenTime('');
      setCategory('vehicle');
    } catch (err: unknown) {
      Alert.alert('Error', errorText(err, 'Could not submit. Try again.'));
    } finally {
      setSubmitting(false);
    }
  }, [category, description, bodyPart, medAttn, tbaCount, location, witness, stolenTime]);

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
        refreshControl={
          tab === 'history'
            ? <RefreshControl refreshing={refreshing} onRefresh={() => fetchHistory({ refresh: true })} tintColor={c.primary} />
            : undefined
        }
      >
        {tab === 'report' ? (
          <>
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
                  <Text style={[s.chipText, category === cat && { color: '#fff' }]}>{CATEGORY_LABELS[cat]}</Text>
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
                  placeholderTextColor={c.mutedForeground}
                />
                <Text style={s.label}>Medical Attention Required?</Text>
                <View style={s.boolRow}>
                  {[true, false].map(val => (
                    <TouchableOpacity
                      key={String(val)}
                      style={[s.boolBtn, medAttn === val && { backgroundColor: c.primary, borderColor: c.primary }]}
                      onPress={() => setMedAttn(val)}
                    >
                      <Text style={[s.boolText, medAttn === val && { color: '#fff' }]}>{val ? 'Yes' : 'No'}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              </>
            )}

            {/* Stolen packages extras */}
            {category === 'stolen_packages' && (
              <>
                <Text style={s.label}>Time of Incident</Text>
                <TextInput style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }]} value={stolenTime} onChangeText={setStolenTime} placeholder="e.g. 2:30 PM" placeholderTextColor={c.mutedForeground} />
                <Text style={s.label}>TBA Count</Text>
                <TextInput style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }]} value={tbaCount} onChangeText={setTbaCount} placeholder="Number of packages" placeholderTextColor={c.mutedForeground} keyboardType="numeric" />
                <Text style={s.label}>Location</Text>
                <TextInput style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }]} value={location} onChangeText={setLocation} placeholder="Street / landmark" placeholderTextColor={c.mutedForeground} />
                <Text style={s.label}>Witness Name</Text>
                <TextInput style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }]} value={witness} onChangeText={setWitness} placeholder="Optional" placeholderTextColor={c.mutedForeground} />
              </>
            )}

            {/* Description */}
            <Text style={s.label}>Description *</Text>
            <TextInput
              style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }]}
              value={description}
              onChangeText={setDescription}
              placeholder="Describe what happened…"
              placeholderTextColor={c.mutedForeground}
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
          </>
        ) : (
          <>
            <Text style={s.pageTitle}>My Incidents</Text>
            {loading ? (
              <ActivityIndicator color={c.primary} style={{ marginTop: spacing.xl }} />
            ) : incidents.length === 0 ? (
              <View style={s.emptyCard}><Text style={s.emptyText}>No incidents filed</Text></View>
            ) : incidents.map(inc => (
              <TouchableOpacity key={inc.id} style={s.incCard} onPress={() => toggle(inc.id)} activeOpacity={0.8}>
                <View style={s.incHeader}>
                  <View style={[s.sevDot, { backgroundColor: SEVERITY_COLOR[inc.severity]?.(c) ?? c.mutedForeground }]} />
                  <View style={{ flex: 1 }}>
                    <Text style={s.incCategory}>{CATEGORY_LABELS[inc.category] ?? inc.category}</Text>
                    <Text style={s.incMeta}>{inc.created_at.split('T')[0]}</Text>
                  </View>
                  <View style={[s.statusBadge, { backgroundColor: inc.status === 'resolved' ? c.success + '22' : c.warning + '22' }]}>
                    <Text style={[s.statusText, { color: inc.status === 'resolved' ? c.success : c.warning }]}>
                      {inc.status}
                    </Text>
                  </View>
                  <Text style={s.chevron}>{expanded.has(inc.id) ? '▲' : '▼'}</Text>
                </View>
                {expanded.has(inc.id) && (
                  <View style={s.incDetail}>
                    <Text style={s.incDesc}>{inc.description}</Text>
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
