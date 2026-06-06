import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, ScrollView, RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type SurveyListItem = {
  id: string;
  date: string;
  expected_count: number;
  response_count: number;
};

type ResponseItem = {
  id: string;
  respondent_name: string;
  truck_name: string | null;
  driver_name: string | null;
  routes_organized: boolean;
  anchor_point_location: boolean;
  supplies_ready: boolean;
  driver_support: boolean;
  notes: string | null;
  submitted_at: string;
};

type MyResponseStatus = {
  responded: boolean;
  response: ResponseItem | null;
};

type AssignmentInfo = {
  truck_name: string | null;
  driver_name: string | null;
};

// ---------------------------------------------------------------------------
// Yes/No toggle
// ---------------------------------------------------------------------------

function YesNoToggle({
  label, value, onChange, disabled,
}: {
  label: string;
  value: boolean | null;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  const c = useColors();
  const s = toggleStyles(c);
  return (
    <View style={s.row}>
      <Text style={s.question}>{label}</Text>
      <View style={s.buttons}>
        <TouchableOpacity
          style={[s.btn, value === true  && s.btnYes]}
          onPress={() => !disabled && onChange(true)}
          disabled={disabled}
          activeOpacity={0.7}
        >
          <Text style={[s.btnText, value === true  && s.btnYesText]}>Yes</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[s.btn, value === false && s.btnNo]}
          onPress={() => !disabled && onChange(false)}
          disabled={disabled}
          activeOpacity={0.7}
        >
          <Text style={[s.btnText, value === false && s.btnNoText]}>No</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const toggleStyles = (c: ThemeColors) => StyleSheet.create({
  row:       { marginBottom: spacing.md },
  question:  { fontSize: fontSize.sm, color: c.foreground, fontWeight: fontWeight.medium, marginBottom: spacing.xs, lineHeight: 20 },
  buttons:   { flexDirection: 'row', gap: spacing.sm },
  btn:       { flex: 1, paddingVertical: spacing.xs + 2, borderRadius: radius.md, borderWidth: 1.5, borderColor: c.border, alignItems: 'center' },
  btnYes:    { backgroundColor: c.success + '20', borderColor: c.success },
  btnNo:     { backgroundColor: c.danger  + '20', borderColor: c.danger  },
  btnText:   { fontSize: fontSize.sm, color: c.mutedForeground, fontWeight: fontWeight.medium },
  btnYesText:{ color: c.success },
  btnNoText: { color: c.danger  },
});

// ---------------------------------------------------------------------------
// Main screen
// ---------------------------------------------------------------------------

export default function DriverSurveyScreen() {
  const c = useColors();
  const { user, employeeId } = useAuth();
  const s = styles(c);

  // Active survey for today
  const [survey,        setSurvey]        = useState<SurveyListItem | null>(null);
  const [myStatus,      setMyStatus]      = useState<MyResponseStatus | null>(null);
  const [assignment,    setAssignment]    = useState<AssignmentInfo | null>(null);
  const [loading,       setLoading]       = useState(true);
  const [refreshing,    setRefreshing]    = useState(false);
  const [submitting,    setSubmitting]    = useState(false);

  // Form state
  const [routesOrganized,     setRoutesOrganized]     = useState<boolean | null>(null);
  const [anchorPointLocation, setAnchorPointLocation] = useState<boolean | null>(null);
  const [suppliesReady,       setSuppliesReady]       = useState<boolean | null>(null);
  const [driverSupport,       setDriverSupport]       = useState<boolean | null>(null);
  const [notes,               setNotes]               = useState('');

  const todayStr = new Date().toISOString().slice(0, 10);

  const loadSurveyData = useCallback(async (opts?: { refresh?: boolean }) => {
    if (opts?.refresh) setRefreshing(true); else setLoading(true);
    try {
      // Fetch survey list and find today's
      const listRes = await apiClient.get<SurveyListItem[]>('/driver-surveys/?limit=10');
      const todaySurvey = (listRes.data ?? []).find((s: SurveyListItem) => s.date === todayStr) ?? null;
      setSurvey(todaySurvey);

      if (todaySurvey) {
        // Check if already responded
        const statusRes = await apiClient.get<MyResponseStatus>(`/driver-surveys/${todaySurvey.id}/my-response`);
        setMyStatus(statusRes.data);

        if (statusRes.data.responded && statusRes.data.response) {
          const r = statusRes.data.response;
          setAssignment({ truck_name: r.truck_name, driver_name: r.driver_name });
        } else {
          // Resolve assignment info for the display header (truck/driver)
          try {
            const dispatchRes = await apiClient.get(`/dispatch/${todayStr}`);
            const myMember = (dispatchRes.data?.truck_assignments ?? [])
              .flatMap((ta: any) =>
                (ta.members ?? []).map((m: any) => ({ ...m, truck: ta.truck_name, driver_name: ta.driver_name ?? null }))
              )
              .find((m: any) => m.employee_id === employeeId);
            if (myMember) {
              setAssignment({ truck_name: myMember.truck, driver_name: myMember.driver_name });
            }
          } catch {
            // non-fatal — assignment header just won't show
          }
        }
      }
    } catch {
      setSurvey(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [todayStr, employeeId]);

  useEffect(() => { loadSurveyData(); }, [loadSurveyData]);

  const handleSubmit = async () => {
    if (
      routesOrganized === null ||
      anchorPointLocation === null ||
      suppliesReady === null ||
      driverSupport === null
    ) {
      Alert.alert('Incomplete', 'Please answer all four questions before submitting.');
      return;
    }
    if (!survey) return;

    Alert.alert(
      'Submit Survey',
      `Your response will be recorded for your assignment on ${survey.date}${
        assignment?.truck_name ? ` (${assignment.truck_name})` : ''
      }. You cannot change it after submitting.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Submit',
          onPress: async () => {
            setSubmitting(true);
            try {
              await apiClient.post(`/driver-surveys/${survey.id}/respond`, {
                routes_organized:      routesOrganized,
                anchor_point_location: anchorPointLocation,
                supplies_ready:        suppliesReady,
                driver_support:        driverSupport,
                notes:                 notes.trim() || null,
              });
              await loadSurveyData();
            } catch (err: any) {
              Alert.alert('Error', err.response?.data?.detail ?? 'Failed to submit. Please try again.');
            } finally {
              setSubmitting(false);
            }
          },
        },
      ]
    );
  };

  // ── Render states ──────────────────────────────────────────────────────────

  if (loading) {
    return (
      <SafeAreaView style={s.safe}>
        <View style={s.center}>
          <ActivityIndicator size="large" color={c.primary} />
        </View>
      </SafeAreaView>
    );
  }

  if (!survey) {
    return (
      <SafeAreaView style={s.safe}>
        <ScrollView
          contentContainerStyle={s.center}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => loadSurveyData({ refresh: true })} tintColor={c.primary} />}
        >
          <Text style={s.emptyIcon}>📋</Text>
          <Text style={s.emptyTitle}>No Survey Today</Text>
          <Text style={s.emptyText}>Management hasn't activated a driver survey for today yet. Pull to refresh.</Text>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // Already responded — read-only view
  if (myStatus?.responded && myStatus.response) {
    const r = myStatus.response;
    return (
      <SafeAreaView style={s.safe}>
        <ScrollView
          contentContainerStyle={s.scroll}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => loadSurveyData({ refresh: true })} tintColor={c.primary} />}
        >
          <View style={s.header}>
            <Text style={s.title}>Driver Survey — {survey.date}</Text>
            <View style={s.submittedBadge}>
              <Text style={s.submittedText}>✅ Submitted</Text>
            </View>
          </View>

          {(r.truck_name || r.driver_name) && (
            <View style={s.infoCard}>
              {r.truck_name  && <Text style={s.infoLine}><Text style={s.infoLabel}>Truck: </Text>{r.truck_name}</Text>}
              {r.driver_name && <Text style={s.infoLine}><Text style={s.infoLabel}>Driver: </Text>{r.driver_name}</Text>}
            </View>
          )}

          <View style={s.card}>
            {[
              { q: 'Routes organized at shift start',  v: r.routes_organized },
              { q: 'Anchor point in good location',    v: r.anchor_point_location },
              { q: 'Rabbit & supplies ready',          v: r.supplies_ready },
              { q: 'Driver support at anchor point',   v: r.driver_support },
            ].map(({ q, v }) => (
              <View key={q} style={s.readOnlyRow}>
                <Text style={s.readOnlyQ}>{q}</Text>
                <Text style={[s.readOnlyA, { color: v ? c.success : c.danger }]}>
                  {v ? 'Yes' : 'No'}
                </Text>
              </View>
            ))}
            {r.notes ? (
              <View style={s.notesReadView}>
                <Text style={s.notesLabel}>Additional notes</Text>
                <Text style={s.notesReadText}>{r.notes}</Text>
              </View>
            ) : null}
          </View>

          <Text style={s.submittedMeta}>
            Submitted {new Date(r.submitted_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </Text>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // Survey form
  return (
    <SafeAreaView style={s.safe}>
      <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
        <View style={s.header}>
          <Text style={s.title}>Driver Survey</Text>
          <Text style={s.subtitle}>{survey.date}</Text>
        </View>

        {/* Assignment info */}
        {assignment && (assignment.truck_name || assignment.driver_name) && (
          <View style={s.infoCard}>
            <Text style={s.infoNote}>
              Your response will be recorded for your primary assignment today.
            </Text>
            {assignment.truck_name  && <Text style={s.infoLine}><Text style={s.infoLabel}>Truck: </Text>{assignment.truck_name}</Text>}
            {assignment.driver_name && <Text style={s.infoLine}><Text style={s.infoLabel}>Driver: </Text>{assignment.driver_name}</Text>}
          </View>
        )}

        <View style={s.card}>
          <YesNoToggle
            label="Were the routes on your truck organized to work from at the start of the shift?"
            value={routesOrganized}
            onChange={setRoutesOrganized}
            disabled={submitting}
          />
          <YesNoToggle
            label="Was your anchor point in a good strategic location?"
            value={anchorPointLocation}
            onChange={setAnchorPointLocation}
            disabled={submitting}
          />
          <YesNoToggle
            label="Was the rabbit and supplies (vest, cart, bike locks, water, etc.) available and ready for use?"
            value={suppliesReady}
            onChange={setSuppliesReady}
            disabled={submitting}
          />
          <YesNoToggle
            label="Did the driver support you well at the anchor point?"
            value={driverSupport}
            onChange={setDriverSupport}
            disabled={submitting}
          />

          {/* Additional notes */}
          <View style={s.notesSection}>
            <Text style={s.notesLabel}>Additional Notes (optional)</Text>
            <TextInput
              style={s.notesInput}
              placeholder="Any additional concerns or observations…"
              placeholderTextColor={c.mutedForeground}
              value={notes}
              onChangeText={setNotes}
              multiline
              numberOfLines={4}
              textAlignVertical="top"
              editable={!submitting}
            />
          </View>
        </View>

        <TouchableOpacity
          style={[s.submitBtn, submitting && s.submitBtnDisabled]}
          onPress={handleSubmit}
          disabled={submitting}
          activeOpacity={0.8}
        >
          {submitting
            ? <ActivityIndicator color="#fff" />
            : <Text style={s.submitText}>Submit Survey</Text>
          }
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:             { flex: 1, backgroundColor: c.background },
  scroll:           { padding: spacing.md, paddingBottom: spacing.xl },
  center:           { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.lg },

  header:           { marginBottom: spacing.md },
  title:            { fontSize: fontSize.xl, fontWeight: fontWeight.bold, color: c.foreground },
  subtitle:         { fontSize: fontSize.sm, color: c.mutedForeground, marginTop: 2 },

  infoCard:         { backgroundColor: c.surface, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md, borderWidth: 1, borderColor: c.border },
  infoNote:         { fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: spacing.xs, fontStyle: 'italic' },
  infoLine:         { fontSize: fontSize.sm, color: c.foreground, marginTop: 2 },
  infoLabel:        { fontWeight: fontWeight.semibold },

  card:             { backgroundColor: c.surface, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md, borderWidth: 1, borderColor: c.border },

  notesSection:     { marginTop: spacing.xs },
  notesLabel:       { fontSize: fontSize.sm, color: c.mutedForeground, fontWeight: fontWeight.medium, marginBottom: spacing.xs },
  notesInput:       { backgroundColor: c.background, borderWidth: 1.5, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm, fontSize: fontSize.sm, color: c.foreground, minHeight: 88 },

  submitBtn:        { backgroundColor: c.primary, borderRadius: radius.lg, paddingVertical: spacing.md, alignItems: 'center', marginTop: spacing.sm },
  submitBtnDisabled:{ opacity: 0.6 },
  submitText:       { color: '#fff', fontSize: fontSize.base, fontWeight: fontWeight.semibold },

  // Read-only submitted view
  submittedBadge:   { marginTop: spacing.xs, alignSelf: 'flex-start', backgroundColor: c.success + '20', paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.sm },
  submittedText:    { fontSize: fontSize.xs, color: c.success, fontWeight: fontWeight.semibold },
  submittedMeta:    { fontSize: fontSize.xs, color: c.subtle, textAlign: 'center', marginTop: spacing.sm },
  readOnlyRow:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: c.border },
  readOnlyQ:        { fontSize: fontSize.sm, color: c.foreground, flex: 1, paddingRight: spacing.sm },
  readOnlyA:        { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  notesReadView:    { marginTop: spacing.md, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: c.border },
  notesReadText:    { fontSize: fontSize.sm, color: c.foreground, fontStyle: 'italic', marginTop: spacing.xs },

  // Empty state
  emptyIcon:        { fontSize: 40, textAlign: 'center', marginBottom: spacing.md },
  emptyTitle:       { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground, textAlign: 'center', marginBottom: spacing.xs },
  emptyText:        { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center', lineHeight: 20 },
});
