import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  useColorScheme, ActivityIndicator, Alert, ScrollView, Modal,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { lightColors, darkColors, spacing, radius, fontSize, fontWeight } from '@theme/index';

// ── Types ─────────────────────────────────────────────────────────────────────
type AP = {
  id: string;
  truck_id: string;
  sequence: number;
  is_initial: boolean;
  status: 'preliminary' | 'arrived' | 'relocated';
  location: string;
  eta: string | null;
  notes: string | null;
  submitted_at: string;
  arrived_at: string | null;
  confirmed_at: string | null;
};

type Crew = {
  truck_id: string | null;
  truck_name: string | null;
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const STATUS_COLOR = (status: string, c: typeof lightColors) => {
  if (status === 'arrived')    return c.success;
  if (status === 'relocated')  return c.mutedForeground;
  return c.warning; // preliminary
};

const STATUS_LABEL: Record<string, string> = {
  preliminary: 'Preliminary',
  arrived:     'Arrived',
  relocated:   'Relocated',
};

function fmtTime(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

// ── Main screen ───────────────────────────────────────────────────────────────
export default function AnchorPointsScreen() {
  const scheme = useColorScheme();
  const c = scheme === 'dark' ? darkColors : lightColors;
  const { user } = useAuth();

  const [employeeId, setEmployeeId] = useState<string | null>(null);
  const [crew,       setCrew]       = useState<Crew | null>(null);
  const [apList,     setApList]     = useState<AP[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Submit AP modal
  const [submitModal, setSubmitModal] = useState(false);
  const [apLocation,  setApLocation]  = useState('');
  const [apEta,       setApEta]       = useState('');
  const [apNotes,     setApNotes]     = useState('');
  const [submitting,  setSubmitting]  = useState(false);

  // Arrive modal
  const [arriveModal,   setArriveModal]   = useState(false);
  const [arriveTarget,  setArriveTarget]  = useState<AP | null>(null);
  const [arriveLocation,setArriveLocation]= useState('');
  const [arriveNotes,   setArriveNotes]   = useState('');
  const [arriving,      setArriving]      = useState(false);

  // Prefill suggestions from previous locations
  const [suggestions, setSuggestions] = useState<string[]>([]);

  // Resolve employee ID + crew info once
  useEffect(() => {
    apiClient.get('/employees/me').then(r => {
      const id = r.data?.id;
      setEmployeeId(id ?? null);
      if (id) {
        apiClient.get(`/field-ops/crew/${id}`).then(cr => {
          setCrew({ truck_id: cr.data?.truck_id ?? null, truck_name: cr.data?.truck_name ?? null });
          // Fetch last-used AP locations for this truck
          if (cr.data?.truck_id) {
            apiClient.get(`/anchor-points/truck/${cr.data.truck_id}?limit=5`)
              .then(h => setSuggestions([...new Set<string>((h.data as AP[]).map((a: AP) => a.location))].slice(0, 4)))
              .catch(() => {});
          }
        }).catch(() => setCrew(null));
      }
    }).catch(() => {});
  }, []);

  const fetchAPs = useCallback(async () => {
    try {
      const res = await apiClient.get('/anchor-points/driver/today');
      setApList(res.data ?? []);
    } catch {
      setApList([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { if (employeeId) fetchAPs(); }, [employeeId, fetchAPs]);

  const onRefresh = useCallback(() => { setRefreshing(true); fetchAPs(); }, [fetchAPs]);

  // Derived: current active AP (not relocated)
  const activeAP = apList.find(ap => ap.status !== 'relocated') ?? null;
  const hasActive = activeAP != null;

  // ── Submit new AP ────────────────────────────────────────────────────────────
  const submitAP = useCallback(async () => {
    if (!apLocation.trim()) { Alert.alert('Required', 'Enter a location.'); return; }
    if (!crew?.truck_id)    { Alert.alert('No Assignment', 'You are not assigned to a truck today.'); return; }
    setSubmitting(true);
    try {
      await apiClient.post('/anchor-points/', {
        truck_id: crew.truck_id,
        date: todayISO(),
        location: apLocation.trim(),
        eta: apEta.trim() || undefined,
        notes: apNotes.trim() || undefined,
      });
      Alert.alert(hasActive ? 'AP Relocated' : 'AP Submitted', 'Crew and dispatch have been notified.');
      setSubmitModal(false);
      setApLocation(''); setApEta(''); setApNotes('');
      fetchAPs();
    } catch (err: any) {
      Alert.alert('Error', err.response?.data?.detail ?? 'Could not submit. Try again.');
    } finally {
      setSubmitting(false);
    }
  }, [apLocation, apEta, apNotes, crew, hasActive, fetchAPs]);

  // ── Confirm arrival ──────────────────────────────────────────────────────────
  const openArrive = (ap: AP) => {
    setArriveTarget(ap);
    setArriveLocation(ap.location);
    setArriveNotes(ap.notes ?? '');
    setArriveModal(true);
  };

  const confirmArrival = useCallback(async () => {
    if (!arriveTarget) return;
    setArriving(true);
    try {
      await apiClient.patch(`/anchor-points/${arriveTarget.id}/arrive`, {
        location: arriveLocation.trim() || undefined,
        notes: arriveNotes.trim() || undefined,
      });
      Alert.alert('Arrived', 'Arrival confirmed. Crew and dispatch notified.');
      setArriveModal(false);
      fetchAPs();
    } catch (err: any) {
      Alert.alert('Error', err.response?.data?.detail ?? 'Could not confirm. Try again.');
    } finally {
      setArriving(false);
    }
  }, [arriveTarget, arriveLocation, arriveNotes, fetchAPs]);

  const s = styles(c);

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        refreshControl={
          <View /> /* pull-to-refresh via header button instead to keep simple */
        }
      >
        {/* Header */}
        <View style={s.header}>
          <View style={{ flex: 1 }}>
            <Text style={s.pageTitle}>Anchor Points</Text>
            {crew?.truck_name ? (
              <Text style={s.subtitle}>{crew.truck_name} · {todayISO()}</Text>
            ) : (
              <Text style={[s.subtitle, { color: c.danger }]}>No truck assignment today</Text>
            )}
          </View>
          <TouchableOpacity style={s.refreshBtn} onPress={() => { setRefreshing(true); fetchAPs(); }}>
            <Text style={{ color: c.primary, fontSize: fontSize.lg }}>↻</Text>
          </TouchableOpacity>
        </View>

        {loading ? (
          <ActivityIndicator color={c.primary} style={{ marginTop: spacing.xl }} />
        ) : (
          <>
            {/* Action buttons */}
            <View style={s.actionRow}>
              <TouchableOpacity
                style={[s.actionBtn, { backgroundColor: c.primary, flex: 1 }]}
                onPress={() => setSubmitModal(true)}
                disabled={!crew?.truck_id}
              >
                <Text style={s.actionBtnText}>
                  {hasActive ? '🔀 Relocate AP' : '📍 Set Anchor Point'}
                </Text>
              </TouchableOpacity>

              {activeAP?.status === 'preliminary' && (
                <TouchableOpacity
                  style={[s.actionBtn, { backgroundColor: c.success, flex: 1 }]}
                  onPress={() => openArrive(activeAP)}
                >
                  <Text style={s.actionBtnText}>✅ Confirm Arrival</Text>
                </TouchableOpacity>
              )}
            </View>

            {/* Active AP card */}
            {activeAP && (
              <View style={[s.activeCard, { borderColor: STATUS_COLOR(activeAP.status, c) }]}>
                <View style={s.activeCardHeader}>
                  <View style={[s.statusDot, { backgroundColor: STATUS_COLOR(activeAP.status, c) }]} />
                  <Text style={[s.activeStatus, { color: STATUS_COLOR(activeAP.status, c) }]}>
                    {STATUS_LABEL[activeAP.status]} · AP #{activeAP.sequence}
                  </Text>
                  {activeAP.confirmed_at && (
                    <View style={[s.confirmedBadge, { backgroundColor: c.success + '20' }]}>
                      <Text style={[s.confirmedText, { color: c.success }]}>Dispatch confirmed</Text>
                    </View>
                  )}
                </View>
                <Text style={s.activeLocation}>{activeAP.location}</Text>
                <View style={s.metaRow}>
                  {activeAP.eta && (
                    <MetaChip icon="🕐" value={`ETA ${activeAP.eta}`} c={c} />
                  )}
                  <MetaChip icon="📤" value={`Submitted ${fmtTime(activeAP.submitted_at)}`} c={c} />
                  {activeAP.arrived_at && (
                    <MetaChip icon="✅" value={`Arrived ${fmtTime(activeAP.arrived_at)}`} c={c} />
                  )}
                </View>
                {activeAP.notes && (
                  <Text style={[s.noteText, { color: c.mutedForeground }]}>{activeAP.notes}</Text>
                )}
              </View>
            )}

            {!hasActive && !loading && (
              <View style={s.emptyCard}>
                <Text style={s.emptyIcon}>📍</Text>
                <Text style={s.emptyTitle}>No anchor point set</Text>
                <Text style={s.emptyBody}>
                  Set your preliminary AP before leaving the station so your crew and dispatch know where you're headed.
                </Text>
              </View>
            )}

            {/* Timeline */}
            {apList.length > 1 && (
              <>
                <Text style={s.sectionLabel}>Today's Timeline</Text>
                {apList.map((ap, idx) => (
                  <TimelineRow key={ap.id} ap={ap} isLast={idx === apList.length - 1} c={c} />
                ))}
              </>
            )}
          </>
        )}
      </ScrollView>

      {/* ── Submit / Relocate AP Modal ── */}
      <Modal visible={submitModal} transparent animationType="slide" onRequestClose={() => setSubmitModal(false)}>
        <View style={s.overlay}>
          <ScrollView style={{ width: '100%' }} contentContainerStyle={{ alignItems: 'center', paddingVertical: spacing.xl }}>
            <View style={[s.modalCard, { backgroundColor: c.card }]}>
              <Text style={[s.modalTitle, { color: c.foreground }]}>
                {hasActive ? 'Relocate Anchor Point' : 'Set Anchor Point'}
              </Text>
              {hasActive && (
                <View style={[s.warningBox, { backgroundColor: c.warning + '18', borderColor: c.warning + '40' }]}>
                  <Text style={[s.warningText, { color: c.warning }]}>
                    This will mark your current AP as relocated and notify your crew.
                  </Text>
                </View>
              )}

              <Text style={s.fieldLabel}>Location *</Text>
              <TextInput
                style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
                value={apLocation}
                onChangeText={setApLocation}
                placeholder="e.g. 5th Ave & 42nd St"
                placeholderTextColor={c.mutedForeground}
              />

              {/* Suggestions from recent APs */}
              {suggestions.length > 0 && (
                <>
                  <Text style={[s.fieldLabel, { marginTop: 0 }]}>Recent locations</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: spacing.sm }}>
                    {suggestions.map(loc => (
                      <TouchableOpacity
                        key={loc}
                        style={[s.suggestionChip, { borderColor: c.border, backgroundColor: c.card }]}
                        onPress={() => setApLocation(loc)}
                      >
                        <Text style={[s.suggestionText, { color: c.foreground }]} numberOfLines={1}>{loc}</Text>
                      </TouchableOpacity>
                    ))}
                  </ScrollView>
                </>
              )}

              <Text style={s.fieldLabel}>ETA (optional)</Text>
              <TextInput
                style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
                value={apEta}
                onChangeText={setApEta}
                placeholder="e.g. 8:30 AM"
                placeholderTextColor={c.mutedForeground}
              />

              <Text style={s.fieldLabel}>Notes (optional)</Text>
              <TextInput
                style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
                value={apNotes}
                onChangeText={setApNotes}
                placeholder="Anything dispatch should know…"
                placeholderTextColor={c.mutedForeground}
                multiline
                numberOfLines={3}
                textAlignVertical="top"
              />

              <View style={s.modalBtns}>
                <TouchableOpacity style={[s.modalBtn, { borderColor: c.border }]} onPress={() => setSubmitModal(false)}>
                  <Text style={[s.modalBtnText, { color: c.foreground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[s.modalBtn, { backgroundColor: c.primary, borderColor: c.primary, opacity: submitting ? 0.6 : 1 }]}
                  onPress={submitAP}
                  disabled={submitting}
                >
                  {submitting
                    ? <ActivityIndicator color="#fff" />
                    : <Text style={[s.modalBtnText, { color: '#fff' }]}>
                        {hasActive ? 'Relocate' : 'Submit'}
                      </Text>
                  }
                </TouchableOpacity>
              </View>
            </View>
          </ScrollView>
        </View>
      </Modal>

      {/* ── Arrive Confirmation Modal ── */}
      <Modal visible={arriveModal} transparent animationType="slide" onRequestClose={() => setArriveModal(false)}>
        <View style={s.overlay}>
          <View style={[s.modalCard, { backgroundColor: c.card }]}>
            <Text style={[s.modalTitle, { color: c.foreground }]}>Confirm Arrival</Text>
            <Text style={[s.modalBody, { color: c.mutedForeground }]}>
              Confirm you've arrived at your anchor point. Update the location if needed.
            </Text>

            <Text style={s.fieldLabel}>Location</Text>
            <TextInput
              style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
              value={arriveLocation}
              onChangeText={setArriveLocation}
              placeholder="Confirm or update location"
              placeholderTextColor={c.mutedForeground}
            />

            <Text style={s.fieldLabel}>Notes (optional)</Text>
            <TextInput
              style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
              value={arriveNotes}
              onChangeText={setArriveNotes}
              placeholder="Any notes for dispatch…"
              placeholderTextColor={c.mutedForeground}
              multiline
              numberOfLines={3}
              textAlignVertical="top"
            />

            <View style={s.modalBtns}>
              <TouchableOpacity style={[s.modalBtn, { borderColor: c.border }]} onPress={() => setArriveModal(false)}>
                <Text style={[s.modalBtnText, { color: c.foreground }]}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.modalBtn, { backgroundColor: c.success, borderColor: c.success, opacity: arriving ? 0.6 : 1 }]}
                onPress={confirmArrival}
                disabled={arriving}
              >
                {arriving
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={[s.modalBtnText, { color: '#fff' }]}>✅ I'm Here</Text>
                }
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// ── Timeline row ──────────────────────────────────────────────────────────────
function TimelineRow({ ap, isLast, c }: { ap: AP; isLast: boolean; c: typeof lightColors }) {
  const dotColor = STATUS_COLOR(ap.status, c);
  return (
    <View style={{ flexDirection: 'row', marginBottom: isLast ? 0 : spacing.xs }}>
      {/* Connector */}
      <View style={{ alignItems: 'center', width: 24, marginRight: spacing.sm }}>
        <View style={[tlStyles.dot, { backgroundColor: dotColor }]} />
        {!isLast && <View style={[tlStyles.line, { backgroundColor: c.border }]} />}
      </View>
      {/* Content */}
      <View style={[tlStyles.card, { backgroundColor: c.card, borderColor: c.border }]}>
        <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
          <Text style={{ fontSize: fontSize.xs, color: dotColor, fontWeight: fontWeight.semibold, textTransform: 'uppercase' }}>
            AP #{ap.sequence} · {STATUS_LABEL[ap.status]}
          </Text>
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>{fmtTime(ap.submitted_at)}</Text>
        </View>
        <Text style={{ fontSize: fontSize.sm, color: c.foreground, marginTop: 2 }}>{ap.location}</Text>
        {ap.eta && <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>ETA {ap.eta}</Text>}
        {ap.arrived_at && (
          <Text style={{ fontSize: fontSize.xs, color: c.success }}>Arrived {fmtTime(ap.arrived_at)}</Text>
        )}
      </View>
    </View>
  );
}

const tlStyles = StyleSheet.create({
  dot:  { width: 10, height: 10, borderRadius: 5, marginTop: 4 },
  line: { width: 2, flex: 1, marginTop: 2 },
  card: { flex: 1, borderRadius: radius.md, borderWidth: 1, padding: spacing.sm, marginBottom: spacing.xs, gap: 2 },
});

// ── Meta chip ─────────────────────────────────────────────────────────────────
function MetaChip({ icon, value, c }: { icon: string; value: string; c: typeof lightColors }) {
  return (
    <View style={[mcStyles.chip, { backgroundColor: c.surfaceMuted }]}>
      <Text style={mcStyles.icon}>{icon}</Text>
      <Text style={[mcStyles.text, { color: c.mutedForeground }]}>{value}</Text>
    </View>
  );
}
const mcStyles = StyleSheet.create({
  chip: { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: radius.full, paddingHorizontal: spacing.sm, paddingVertical: 3, marginRight: spacing.xs },
  icon: { fontSize: 11 },
  text: { fontSize: fontSize.xs },
});

// ── Styles ────────────────────────────────────────────────────────────────────
const styles = (c: typeof lightColors) => StyleSheet.create({
  safe:            { flex: 1, backgroundColor: c.background },
  scroll:          { flex: 1 },
  content:         { padding: spacing.lg, paddingBottom: spacing.xxl },
  header:          { flexDirection: 'row', alignItems: 'center', marginBottom: spacing.lg },
  pageTitle:       { fontSize: fontSize.xxl, fontWeight: fontWeight.extrabold, color: c.foreground },
  subtitle:        { fontSize: fontSize.sm, color: c.mutedForeground, marginTop: 2 },
  refreshBtn:      { padding: spacing.sm },
  actionRow:       { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md },
  actionBtn:       { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', paddingHorizontal: spacing.md },
  actionBtnText:   { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  activeCard:      { borderWidth: 2, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.lg, backgroundColor: c.card },
  activeCardHeader:{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.xs },
  statusDot:       { width: 8, height: 8, borderRadius: 4 },
  activeStatus:    { fontSize: fontSize.xs, fontWeight: fontWeight.bold, textTransform: 'uppercase', letterSpacing: 0.6, flex: 1 },
  confirmedBadge:  { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  confirmedText:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  activeLocation:  { fontSize: fontSize.xl, fontWeight: fontWeight.bold, color: c.foreground, marginBottom: spacing.sm },
  metaRow:         { flexDirection: 'row', flexWrap: 'wrap', marginBottom: spacing.xs },
  noteText:        { fontSize: fontSize.xs, fontStyle: 'italic', marginTop: spacing.xs },
  sectionLabel:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: spacing.sm, marginTop: spacing.sm },
  emptyCard:       { backgroundColor: c.surfaceMuted, borderRadius: radius.xl, padding: spacing.xl, alignItems: 'center', marginTop: spacing.md, gap: spacing.sm },
  emptyIcon:       { fontSize: 40 },
  emptyTitle:      { fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.foreground },
  emptyBody:       { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center', lineHeight: 20 },
  // Modal
  overlay:         { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'center', alignItems: 'center' },
  modalCard:       { width: '90%', borderRadius: radius.xl, padding: spacing.lg, gap: spacing.sm },
  modalTitle:      { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  modalBody:       { fontSize: fontSize.sm, lineHeight: 20 },
  warningBox:      { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm },
  warningText:     { fontSize: fontSize.xs, lineHeight: 18 },
  fieldLabel:      { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.foreground, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: spacing.sm, marginBottom: spacing.xs },
  input:           { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, fontSize: fontSize.sm, marginBottom: spacing.xs },
  textArea:        { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, fontSize: fontSize.sm, minHeight: 80, marginBottom: spacing.xs },
  suggestionChip:  { borderWidth: 1, borderRadius: radius.full, paddingHorizontal: spacing.md, paddingVertical: spacing.xs, marginRight: spacing.xs, maxWidth: 180 },
  suggestionText:  { fontSize: fontSize.xs },
  modalBtns:       { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  modalBtn:        { flex: 1, borderWidth: 1, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center' },
  modalBtnText:    { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
});
