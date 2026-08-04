import React, { useState, useEffect, useCallback } from 'react';
import { errorText } from '@api/errorText';
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  TextInput, Alert, ActivityIndicator, RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import apiClient from '@api/client';
import { spacing, fontSize, fontWeight, radius, type ThemeColors } from '@theme/index';
import PageHeader from '@components/ui/PageHeader';

// ── Types ─────────────────────────────────────────────────────────────────────
type RequestType = 'add_day' | 'drop_day' | 'full_rework';
type Status = 'pending' | 'approved' | 'rejected';

interface SCR {
  id: string;
  request_type: RequestType;
  status: Status;
  reason: string | null;
  days_to_add: string[];
  days_to_drop: string[];
  proposed_schedule: string[];
  created_at: string;
  employee?: { name: string; role: string };
}

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

const TYPE_LABEL: Record<RequestType, string> = {
  add_day:     'Add Working Days',
  drop_day:    'Drop Working Days',
  full_rework: 'Full Schedule Rework',
};

const TYPE_DESC: Record<RequestType, string> = {
  add_day:     'Re-enable days you currently have off.',
  drop_day:    'Remove days from your working week.',
  full_rework: 'Replace your entire recurring schedule.',
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function statusColor(status: Status, c: ThemeColors): string {
  if (status === 'approved') return c.success;
  if (status === 'rejected') return c.danger;
  return c.warning;
}

function statusBg(status: Status, c: ThemeColors): string {
  if (status === 'approved') return c.successLight ?? c.success + '22';
  if (status === 'rejected') return c.dangerLight  ?? c.danger  + '22';
  return c.warningLight ?? c.warning + '22';
}

// ── Field staff view ──────────────────────────────────────────────────────────
function FieldStaffView({ c }: { c: ThemeColors }) {
  const s = styles(c);
  const [myId,       setMyId]       = useState('');
  const [offDays,    setOffDays]    = useState<string[]>([]);
  const [requests,   setRequests]   = useState<SCR[]>([]);
  const [mode,       setMode]       = useState<RequestType>('drop_day');
  const [selected,   setSelected]   = useState<string[]>([]);
  const [reason,     setReason]     = useState('');
  const [error,      setError]      = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const workingDays = DAYS.filter(d => !offDays.includes(d));
  const selectableDays = mode === 'add_day' ? offDays : mode === 'drop_day' ? workingDays : DAYS;
  const hasPending = requests.some(r => r.status === 'pending');

  const load = useCallback(async (id: string, opts?: { refresh?: boolean }) => {
    if (opts?.refresh) setRefreshing(true);
    try {
      const [offRes, reqRes] = await Promise.all([
        apiClient.get(`/employee-off-days/${id}`),
        apiClient.get(`/schedule-change-requests/employee/${id}`),
      ]);
      setOffDays(offRes.data.map((o: any) => o.day_of_week));
      setRequests(reqRes.data);
    } catch { /* silently ignore */ }
    finally { setRefreshing(false); }
  }, []);

  useEffect(() => {
    apiClient.get('/employees/me')
      .then(res => {
        setMyId(res.data.id);
        load(res.data.id).finally(() => setLoading(false));
      })
      .catch(() => setLoading(false));
  }, [load]);

  const toggleDay = (day: string) => {
    setSelected(prev => prev.includes(day) ? prev.filter(d => d !== day) : [...prev, day]);
  };

  const handleModeChange = (m: RequestType) => {
    setMode(m);
    setSelected([]);
    setError('');
  };

  const handleSubmit = async () => {
    if (selected.length === 0) { setError('Select at least one day.'); return; }
    if (hasPending) { setError('Cancel your pending request before submitting a new one.'); return; }
    setError('');
    setSubmitting(true);
    try {
      await apiClient.post('/schedule-change-requests/', {
        employee_id: myId,
        request_type: mode,
        reason: reason || undefined,
        days_to_add:       mode === 'add_day'     ? selected : [],
        days_to_drop:      mode === 'drop_day'    ? selected : [],
        proposed_schedule: mode === 'full_rework' ? selected : undefined,
      });
      setSelected([]);
      setReason('');
      load(myId);
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to submit request.'));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCancel = (id: string) => {
    Alert.alert('Cancel Request', 'Are you sure you want to cancel this schedule change request?', [
      { text: 'No', style: 'cancel' },
      {
        text: 'Yes, Cancel',
        style: 'destructive',
        onPress: async () => {
          try {
            await apiClient.delete(`/schedule-change-requests/${id}`);
            load(myId);
          } catch (err: unknown) {
            Alert.alert('Error', errorText(err, 'Failed to cancel.'));
          }
        },
      },
    ]);
  };

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator size="large" color={c.primary} />
      </View>
    );
  }

  return (
    <ScrollView
      style={s.scroll}
      contentContainerStyle={s.content}
      showsVerticalScrollIndicator={false}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={() => { if (myId) load(myId, { refresh: true }); }} tintColor={c.primary} />
      }
    >
      {/* Request type selector */}
      <View style={s.section}>
        <Text style={s.sectionTitle}>Request Type</Text>
        {(['drop_day', 'add_day', 'full_rework'] as RequestType[]).map(m => (
          <TouchableOpacity
            key={m}
            style={[s.typeRow, mode === m && { backgroundColor: c.primary + '14', borderColor: c.primary }]}
            onPress={() => handleModeChange(m)}
            activeOpacity={0.7}
          >
            <View style={[s.radio, mode === m && { borderColor: c.primary }]}>
              {mode === m && <View style={[s.radioDot, { backgroundColor: c.primary }]} />}
            </View>
            <View style={{ flex: 1 }}>
              <Text style={[s.typeLabel, mode === m && { color: c.primary }]}>{TYPE_LABEL[m]}</Text>
              <Text style={s.typeDesc}>{TYPE_DESC[m]}</Text>
            </View>
          </TouchableOpacity>
        ))}
      </View>

      {/* Day picker */}
      <View style={s.section}>
        <Text style={s.sectionTitle}>Select Days</Text>
        {selectableDays.length === 0 ? (
          <Text style={s.emptyText}>No days available for this request type.</Text>
        ) : (
          <View style={s.dayGrid}>
            {selectableDays.map(day => {
              const active = selected.includes(day);
              return (
                <TouchableOpacity
                  key={day}
                  style={[s.dayChip, active && { backgroundColor: c.primary, borderColor: c.primary }]}
                  onPress={() => toggleDay(day)}
                  activeOpacity={0.7}
                >
                  <Text style={[s.dayChipText, active && { color: '#fff' }]}>{day.slice(0, 3)}</Text>
                </TouchableOpacity>
              );
            })}
          </View>
        )}
      </View>

      {/* Reason */}
      <View style={s.section}>
        <Text style={s.sectionTitle}>Reason <Text style={s.optional}>(optional)</Text></Text>
        <TextInput
          style={s.input}
          value={reason}
          onChangeText={setReason}
          placeholder="Briefly explain your request…"
          placeholderTextColor={c.mutedForeground}
          multiline
          numberOfLines={3}
        />
      </View>

      {error ? <Text style={s.errorText}>{error}</Text> : null}

      <TouchableOpacity
        style={[s.submitBtn, (submitting || hasPending) && s.submitBtnDisabled]}
        onPress={handleSubmit}
        disabled={submitting || hasPending}
        activeOpacity={0.8}
      >
        {submitting
          ? <ActivityIndicator size="small" color="#fff" />
          : <Text style={s.submitBtnText}>Submit Request</Text>
        }
      </TouchableOpacity>

      {hasPending && (
        <Text style={[s.hintText, { color: c.warning }]}>
          You have a pending request. Cancel it before submitting a new one.
        </Text>
      )}

      {/* My request history */}
      {requests.length > 0 && (
        <View style={s.section}>
          <Text style={s.sectionTitle}>My Requests</Text>
          {requests.map(r => (
            <View key={r.id} style={s.requestCard}>
              <View style={s.requestHeader}>
                <Text style={s.requestType}>{TYPE_LABEL[r.request_type as RequestType]}</Text>
                <View style={[s.statusBadge, { backgroundColor: statusBg(r.status, c) }]}>
                  <Text style={[s.statusText, { color: statusColor(r.status, c) }]}>
                    {r.status}
                  </Text>
                </View>
              </View>
              {r.days_to_add?.length > 0    && <Text style={s.requestMeta}>Add: {r.days_to_add.join(', ')}</Text>}
              {r.days_to_drop?.length > 0   && <Text style={s.requestMeta}>Drop: {r.days_to_drop.join(', ')}</Text>}
              {r.proposed_schedule?.length > 0 && <Text style={s.requestMeta}>New schedule: {r.proposed_schedule.join(', ')}</Text>}
              {r.reason && <Text style={s.requestReason}>"{r.reason}"</Text>}
              {r.status === 'pending' && (
                <TouchableOpacity style={s.cancelBtn} onPress={() => handleCancel(r.id)} activeOpacity={0.7}>
                  <Text style={[s.cancelBtnText, { color: c.danger }]}>Cancel Request</Text>
                </TouchableOpacity>
              )}
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

// ── Privileged view (dispatch / management / admin) ───────────────────────────
function PrivilegedView({ c }: { c: ThemeColors }) {
  const s = styles(c);
  const [pending,    setPending]    = useState<SCR[]>([]);
  const [all,        setAll]        = useState<SCR[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (opts?: { refresh?: boolean }) => {
    if (opts?.refresh) setRefreshing(true);
    try {
      const [pendRes, allRes] = await Promise.all([
        apiClient.get('/schedule-change-requests/', { params: { status: 'pending' } }),
        apiClient.get('/schedule-change-requests/'),
      ]);
      setPending(pendRes.data);
      setAll(allRes.data);
    } catch { /* silently ignore */ }
    finally { setLoading(false); setRefreshing(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleReview = (id: string, action: 'approve' | 'reject') => {
    const label = action === 'approve' ? 'Approve' : 'Reject';
    Alert.alert(`${label} Request`, `${label} this schedule change request?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: label,
        style: action === 'approve' ? 'default' : 'destructive',
        onPress: async () => {
          try {
            await apiClient.patch(`/schedule-change-requests/${id}/${action}`);
            load();
          } catch (err: unknown) {
            Alert.alert('Error', errorText(err, `Failed to ${action}.`));
          }
        },
      },
    ]);
  };

  const total    = all.length;
  const approved = all.filter(r => r.status === 'approved').length;
  const rejected = all.filter(r => r.status === 'rejected').length;
  const rate     = (approved + rejected) > 0 ? Math.round((approved / (approved + rejected)) * 100) : null;

  if (loading) {
    return <View style={s.center}><ActivityIndicator size="large" color={c.primary} /></View>;
  }

  return (
    <ScrollView
      style={s.scroll}
      contentContainerStyle={s.content}
      showsVerticalScrollIndicator={false}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={() => load({ refresh: true })} tintColor={c.primary} />
      }
    >
      {/* Stats */}
      <View style={s.statsRow}>
        {[
          { label: 'Total',    value: total,                color: c.primary  },
          { label: 'Pending',  value: pending.length,       color: c.warning  },
          { label: 'Approved', value: approved,             color: c.success  },
          { label: 'Rate',     value: rate != null ? `${rate}%` : '—', color: c.foreground },
        ].map(stat => (
          <View key={stat.label} style={[s.statCard, { borderColor: c.border }]}>
            <Text style={[s.statValue, { color: stat.color }]}>{stat.value}</Text>
            <Text style={s.statLabel}>{stat.label}</Text>
          </View>
        ))}
      </View>

      {/* Pending queue */}
      <View style={s.section}>
        <Text style={s.sectionTitle}>Pending Requests</Text>
        {pending.length === 0 ? (
          <Text style={s.emptyText}>No pending requests.</Text>
        ) : (
          pending.map(r => (
            <View key={r.id} style={s.requestCard}>
              <View style={s.requestHeader}>
                <View>
                  <Text style={s.requestType}>{r.employee?.name ?? '—'}</Text>
                  <Text style={s.requestMeta}>{r.employee?.role} · {TYPE_LABEL[r.request_type as RequestType]}</Text>
                </View>
                <View style={[s.statusBadge, { backgroundColor: statusBg(r.status, c) }]}>
                  <Text style={[s.statusText, { color: statusColor(r.status, c) }]}>{r.status}</Text>
                </View>
              </View>
              {r.days_to_add?.length > 0      && <Text style={s.requestMeta}>Add: {r.days_to_add.join(', ')}</Text>}
              {r.days_to_drop?.length > 0     && <Text style={s.requestMeta}>Drop: {r.days_to_drop.join(', ')}</Text>}
              {r.proposed_schedule?.length > 0 && <Text style={s.requestMeta}>New schedule: {r.proposed_schedule.join(', ')}</Text>}
              {r.reason && <Text style={s.requestReason}>"{r.reason}"</Text>}
              <View style={s.reviewBtns}>
                <TouchableOpacity
                  style={[s.reviewBtn, { backgroundColor: c.primary }]}
                  onPress={() => handleReview(r.id, 'approve')}
                  activeOpacity={0.8}
                >
                  <Text style={s.reviewBtnText}>Approve</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[s.reviewBtn, { backgroundColor: c.danger + '18', borderWidth: 1, borderColor: c.danger }]}
                  onPress={() => handleReview(r.id, 'reject')}
                  activeOpacity={0.8}
                >
                  <Text style={[s.reviewBtnText, { color: c.danger }]}>Reject</Text>
                </TouchableOpacity>
              </View>
            </View>
          ))
        )}
      </View>
    </ScrollView>
  );
}

// ── Root screen ───────────────────────────────────────────────────────────────
export default function ScheduleChangesScreen() {
  const c = useColors();
  const { hasRole } = useAuth();
  const s = styles(c);
  const isPrivileged = hasRole('dispatch', 'management', 'admin');

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <PageHeader
        title={isPrivileged ? 'Change Requests' : 'Schedule Changes'}
        subtitle={isPrivileged ? 'Review pending requests' : 'Request a change to your weekly schedule'}
      />
      {isPrivileged ? <PrivilegedView c={c} /> : <FieldStaffView c={c} />}
    </SafeAreaView>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const styles = (c: ThemeColors) => StyleSheet.create({
  safe:              { flex: 1, backgroundColor: c.background },
  header:            { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.sm, borderBottomWidth: 1, borderBottomColor: c.border },
  title:             { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  subtitle:          { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  scroll:            { flex: 1 },
  content:           { padding: spacing.md, paddingBottom: 80 },
  center:            { flex: 1, justifyContent: 'center', alignItems: 'center' },
  section:           { marginBottom: spacing.lg },
  sectionTitle:      { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: spacing.sm },
  optional:          { fontWeight: fontWeight.regular, textTransform: 'none', letterSpacing: 0 },

  // Type selector
  typeRow:           { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm, padding: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, marginBottom: spacing.xs, backgroundColor: c.surface },
  radio:             { width: 18, height: 18, borderRadius: 9, borderWidth: 2, borderColor: c.border, alignItems: 'center', justifyContent: 'center', marginTop: 2 },
  radioDot:          { width: 8, height: 8, borderRadius: 4 },
  typeLabel:         { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground },
  typeDesc:          { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },

  // Day grid
  dayGrid:           { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  dayChip:           { paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, borderRadius: radius.full, borderWidth: 1, borderColor: c.border, backgroundColor: c.surface },
  dayChipText:       { fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.foreground },

  // Input
  input:             { borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm, color: c.foreground, backgroundColor: c.surface, fontSize: fontSize.sm, minHeight: 72, textAlignVertical: 'top' },

  // Submit
  submitBtn:         { backgroundColor: c.primary, borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', marginBottom: spacing.xs },
  submitBtnDisabled: { opacity: 0.5 },
  // `primaryForeground`, not '#fff' — 2.82:1 on dark `primary` (ADR-255).
  submitBtnText:     { color: c.primaryForeground, fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  hintText:          { fontSize: fontSize.xs, textAlign: 'center', marginBottom: spacing.md },
  errorText:         { fontSize: fontSize.xs, color: c.danger, marginBottom: spacing.sm },

  // Request cards
  requestCard:       { backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.sm },
  requestHeader:     { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: spacing.xs },
  requestType:       { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground },
  requestMeta:       { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  requestReason:     { fontSize: fontSize.xs, color: c.mutedForeground, fontStyle: 'italic', marginTop: spacing.xs },
  statusBadge:       { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  statusText:        { fontSize: 10, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  cancelBtn:         { marginTop: spacing.sm, paddingVertical: spacing.xs },
  cancelBtnText:     { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  // Privileged stats
  statsRow:          { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.lg },
  statCard:          { flex: 1, backgroundColor: c.surface, borderRadius: radius.md, borderWidth: 1, padding: spacing.sm, alignItems: 'center' },
  statValue:         { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  statLabel:         { fontSize: 10, color: c.mutedForeground, marginTop: 2 },

  // Review buttons
  reviewBtns:        { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  reviewBtn:         { flex: 1, paddingVertical: spacing.xs + 2, borderRadius: radius.md, alignItems: 'center' },
  reviewBtnText:     { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: '#fff' },

  // Empty
  emptyText:         { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center', paddingVertical: spacing.md },
});
