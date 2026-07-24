import React, { useEffect, useState, useCallback, useRef } from 'react';
import { errorText } from '@api/errorText';
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  ActivityIndicator, RefreshControl, Modal,
  TextInput, Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuth } from '@contexts/AuthContext';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, getRoleColor, type ThemeColors, type FieldRole } from '@theme/index';
import PageHeader from '@components/ui/PageHeader';

// ── Types ─────────────────────────────────────────────────────────────────────
type CrewMember = { id: string; name: string; role: string };
type ScheduleEntry = {
  date: string;
  status: string;
  truck_name?: string | null;
  crew?: CrewMember[];
};
type PTORequest = { id: string; date: string; status: 'pending' | 'approved' | 'rejected' };
type SCR = {
  id: string;
  request_type: 'add_day' | 'drop_day' | 'full_rework';
  days_to_add: string[];
  days_to_drop: string[];
  proposed_schedule: string[] | null;
  reason: string | null;
  status: string;
  created_at: string;
};

// ── Constants ─────────────────────────────────────────────────────────────────
const DAYS    = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS  = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const MONTHS_SHORT = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const WEEKDAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];

const ROLE_LABELS: Record<string, string> = {
  driver: 'Driver', trainer: 'Trainer', trainee: 'Trainee', walker: 'Walker',
};
const SCR_TYPE_LABELS: Record<string, string> = {
  add_day: 'Add Work Day', drop_day: 'Drop Work Day', full_rework: 'Full Rework',
};
const OFF_STATUSES = new Set(['Off (Recurring)', 'Time Off', 'Pending Time Off', 'Pending Off (Recurring)']);

function statusColor(status: string, c: ThemeColors): string {
  if (status === 'approved') return c.success;
  if (status === 'rejected') return c.danger;
  return c.warning;
}
function formatFullDate(iso: string): string {
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
}

// ── Main screen ───────────────────────────────────────────────────────────────
export default function ScheduleScreen() {
  const c = useColors();
  const { user } = useAuth();

  const today    = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

  const [viewMonth,    setViewMonth]    = useState(today.getMonth());
  const [viewYear,     setViewYear]     = useState(today.getFullYear());
  const [schedule,     setSchedule]     = useState<ScheduleEntry[]>([]);
  const [ptoList,      setPtoList]      = useState<PTORequest[]>([]);
  const [scrList,      setScrList]      = useState<SCR[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [refreshing,   setRefreshing]   = useState(false);
  const [fetchError,   setFetchError]   = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(todayStr);

  // Cognito sub != Employee DB id — fetch the real employee UUID once and cache it
  const employeeDbId = useRef<string | null>(null);

  // PTO modal
  const [ptoModal,      setPtoModal]      = useState(false);
  const [ptoSubmitting, setPtoSubmitting] = useState(false);

  // SCR modal
  const [scrModal,      setScrModal]      = useState(false);
  const [scrType,       setScrType]       = useState<'add_day'|'drop_day'|'full_rework'>('add_day');
  const [scrDaysAdd,    setScrDaysAdd]    = useState<string[]>([]);
  const [scrDaysDrop,   setScrDaysDrop]  = useState<string[]>([]);
  const [scrProposed,   setScrProposed]  = useState<string[]>([]);
  const [scrReason,     setScrReason]    = useState('');
  const [scrSubmitting, setScrSubmitting] = useState(false);

  const [subTab, setSubTab] = useState<'pto'|'schedule'>('pto');

  const fetchSchedule = useCallback(async () => {
    if (!user) return;
    try {
      // Resolve the employee's database UUID on first load
      if (!employeeDbId.current) {
        const meRes = await apiClient.get('/employees/me');
        employeeDbId.current = meRes.data.id;
      }
      const employeeId = employeeDbId.current!;

      const firstOfMonth = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}-01`;
      const lastDay      = new Date(viewYear, viewMonth + 1, 0).getDate();
      const lastOfMonth  = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
      const [schedRes, ptoRes, scrRes] = await Promise.all([
        apiClient.get(`/schedule/${employeeId}?start_date=${firstOfMonth}&end_date=${lastOfMonth}`),
        apiClient.get(`/time-off-requests/${employeeId}`),
        apiClient.get(`/schedule-change-requests/employee/${employeeId}`),
      ]);
      setSchedule(schedRes.data ?? []);
      setPtoList(ptoRes.data ?? []);
      setScrList(scrRes.data ?? []);
      setFetchError(null);
    } catch (err: unknown) {
      setSchedule([]);
      setFetchError(errorText(err, 'Failed to load schedule.'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [user, viewMonth, viewYear]);

  useEffect(() => {
    if (user) { setLoading(true); fetchSchedule(); }
  }, [fetchSchedule]);

  const onRefresh = useCallback(() => { setRefreshing(true); fetchSchedule(); }, [fetchSchedule]);

  // ── Calendar state helpers ──────────────────────────────────────────────────
  const scheduleMap   = new Map(schedule.map(e => [String(e.date).slice(0, 10), e]));
  const ptoPending    = new Set(ptoList.filter(p => p.status === 'pending').map(p => p.date));
  const ptoApproved   = new Set(ptoList.filter(p => p.status === 'approved').map(p => p.date));

  const prevMonth = () => {
    if (viewMonth === 0) { setViewMonth(11); setViewYear(y => y - 1); }
    else setViewMonth(m => m - 1);
  };
  const nextMonth = () => {
    if (viewMonth === 11) { setViewMonth(0); setViewYear(y => y + 1); }
    else setViewMonth(m => m + 1);
  };

  const firstDay    = new Date(viewYear, viewMonth, 1).getDay();
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

  const onDayPress = (dateStr: string) => {
    setSelectedDate(dateStr);
    const entry = scheduleMap.get(dateStr);
    const isOff       = entry ? OFF_STATUSES.has(entry.status) : false;
    const isPtoPend   = ptoPending.has(dateStr);
    const isPtoApp    = ptoApproved.has(dateStr);
    const isFuture    = dateStr > todayStr;
    const isWorkday   = entry && !isOff;
    // Open PTO modal for future working days that aren't already requested
    if (isFuture && isWorkday && !isPtoApp && !isPtoPend) {
      setPtoModal(true);
    }
  };

  // ── PTO submit ──────────────────────────────────────────────────────────────
  const submitPTO = useCallback(async () => {
    if (!employeeDbId.current) return;
    setPtoSubmitting(true);
    try {
      await apiClient.post('/time-off-requests/', { employee_id: employeeDbId.current, date: selectedDate });
      Alert.alert('Submitted', `PTO request for ${selectedDate} sent to management.`);
      setPtoModal(false);
      fetchSchedule();
    } catch (err: unknown) {
      Alert.alert('Error', errorText(err, 'Could not submit. Try again.'));
    } finally {
      setPtoSubmitting(false);
    }
  }, [selectedDate, fetchSchedule]);

  const cancelPTO = useCallback(async (id: string) => {
    Alert.alert('Cancel Request', 'Remove this PTO request?', [
      { text: 'No', style: 'cancel' },
      { text: 'Yes, Cancel', style: 'destructive', onPress: async () => {
        try { await apiClient.delete(`/time-off-requests/${id}`); fetchSchedule(); }
        catch { Alert.alert('Error', 'Could not cancel request.'); }
      }},
    ]);
  }, [fetchSchedule]);

  // ── SCR submit ──────────────────────────────────────────────────────────────
  const submitSCR = useCallback(async () => {
    if (!employeeDbId.current) return;
    if (scrType === 'add_day'     && scrDaysAdd.length === 0)  { Alert.alert('Required', 'Select at least one day to add.'); return; }
    if (scrType === 'drop_day'    && scrDaysDrop.length === 0) { Alert.alert('Required', 'Select at least one day to drop.'); return; }
    if (scrType === 'full_rework' && scrProposed.length === 0) { Alert.alert('Required', 'Select your proposed schedule days.'); return; }
    setScrSubmitting(true);
    try {
      await apiClient.post('/schedule-change-requests/', {
        employee_id: employeeDbId.current, request_type: scrType,
        days_to_add: scrType === 'add_day' ? scrDaysAdd : [],
        days_to_drop: scrType === 'drop_day' ? scrDaysDrop : [],
        proposed_schedule: scrType === 'full_rework' ? scrProposed : undefined,
        reason: scrReason || undefined,
      });
      Alert.alert('Submitted', 'Schedule change request sent to management.');
      setScrModal(false);
      setScrDaysAdd([]); setScrDaysDrop([]); setScrProposed([]); setScrReason('');
      fetchSchedule();
    } catch (err: unknown) {
      Alert.alert('Error', errorText(err, 'Could not submit. Try again.'));
    } finally {
      setScrSubmitting(false);
    }
  }, [scrType, scrDaysAdd, scrDaysDrop, scrProposed, scrReason, fetchSchedule]);

  const toggleDay = (day: string, list: string[], setter: (l: string[]) => void) =>
    setter(list.includes(day) ? list.filter(d => d !== day) : [...list, day]);

  const s = styles(c);
  const selectedEntry = scheduleMap.get(selectedDate);

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <PageHeader title="Schedule" subtitle={`${MONTHS[viewMonth]} ${viewYear}`} />

      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.primary} />}
      >
        {/* Month navigator */}
        <View style={s.monthNav}>
          <TouchableOpacity onPress={prevMonth} style={s.navBtn} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
            <Text style={[s.navArrow, { color: c.primary }]}>‹</Text>
          </TouchableOpacity>
          <Text style={s.monthLabel}>{MONTHS_SHORT[viewMonth]} {viewYear}</Text>
          <TouchableOpacity onPress={nextMonth} style={s.navBtn} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
            <Text style={[s.navArrow, { color: c.primary }]}>›</Text>
          </TouchableOpacity>
        </View>

        {/* Calendar */}
        <View style={s.calCard}>
          {/* Day-of-week headers */}
          <View style={s.gridRow}>
            {DAYS.map(d => (
              <View key={d} style={s.gridCell}>
                <Text style={s.dayHeader}>{d}</Text>
              </View>
            ))}
          </View>

          {/* Day cells — grouped into rows of 7 */}
          {buildWeeks(firstDay, daysInMonth).map((week, wi) => (
            <View key={wi} style={s.gridRow}>
              {week.map((day, di) => {
                if (day === null) return <View key={di} style={s.gridCell} />;
                const dateStr   = `${viewYear}-${String(viewMonth + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
                const entry     = scheduleMap.get(dateStr);
                const isOff     = entry ? OFF_STATUSES.has(entry.status) : false;
                const isWorkday = !!entry && !isOff;
                const isPtoPend = ptoPending.has(dateStr);
                const isPtoApp  = ptoApproved.has(dateStr);
                const isToday   = dateStr === todayStr;
                const isSelected = dateStr === selectedDate;

                let circleStyle: object = {};
                let textColor = c.foreground;

                if (isSelected && isToday) {
                  circleStyle = { backgroundColor: c.primary };
                  textColor   = '#fff';
                } else if (isSelected) {
                  circleStyle = { backgroundColor: c.primary + '22', borderWidth: 1.5, borderColor: c.primary };
                  textColor   = c.primary;
                } else if (isToday) {
                  circleStyle = { backgroundColor: c.primary };
                  textColor   = '#fff';
                } else if (isPtoApp || isOff) {
                  circleStyle = { borderWidth: 1, borderColor: c.danger + '60', backgroundColor: c.danger + '12' };
                  textColor   = c.danger;
                } else if (isPtoPend) {
                  circleStyle = { borderWidth: 1, borderColor: c.warning + '80', backgroundColor: c.warning + '15' };
                  textColor   = c.warning;
                } else if (isWorkday) {
                  circleStyle = { borderWidth: 1, borderColor: c.success + '70', backgroundColor: c.success + '18' };
                  textColor   = c.success;
                }

                return (
                  <TouchableOpacity
                    key={di}
                    style={s.gridCell}
                    onPress={() => onDayPress(dateStr)}
                    activeOpacity={0.65}
                  >
                    <View style={[s.dayCircle, circleStyle]}>
                      <Text style={[s.dateText, { color: textColor }, isToday && { fontWeight: fontWeight.bold }]}>
                        {day}
                      </Text>
                    </View>
                  </TouchableOpacity>
                );
              })}
            </View>
          ))}
        </View>

        {loading && <ActivityIndicator color={c.primary} style={{ marginVertical: spacing.md }} />}

        {fetchError && (
          <View style={{ backgroundColor: c.danger + '18', borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.sm, borderWidth: 1, borderColor: c.danger + '40' }}>
            <Text style={{ fontSize: fontSize.xs, color: c.danger }}>{fetchError}</Text>
          </View>
        )}

        {/* Legend */}
        <View style={s.legend}>
          {[
            { color: c.success, label: 'Workday' },
            { color: c.primary, label: 'Today' },
            { color: c.warning, label: 'PTO Pending' },
            { color: c.danger,  label: 'Off / PTO' },
          ].map(({ color, label }) => (
            <View key={label} style={s.legendItem}>
              <View style={[s.legendDot, { backgroundColor: color }]} />
              <Text style={s.legendText}>{label}</Text>
            </View>
          ))}
        </View>

        {/* Selected day detail card */}
        {selectedEntry ? (
          <SelectedDayCard entry={selectedEntry} dateStr={selectedDate} c={c} />
        ) : (
          <View style={[s.selectedCard, { backgroundColor: c.card, borderColor: c.border }]}>
            <Text style={[s.selectedDateLabel, { color: c.foreground }]}>{formatFullDate(selectedDate)}</Text>
            <Text style={[s.selectedEmpty, { color: c.mutedForeground }]}>No schedule data for this day</Text>
          </View>
        )}

        <Text style={s.hint}>Tap a scheduled workday to request time off.</Text>

        {/* Sub-tab bar */}
        <View style={s.subTabBar}>
          {(['pto', 'schedule'] as const).map(t => (
            <TouchableOpacity
              key={t}
              style={[s.subTab, subTab === t && s.subTabActive]}
              onPress={() => setSubTab(t)}
            >
              <Text style={[s.subTabText, subTab === t && { color: c.primary, fontWeight: fontWeight.semibold }]}>
                {t === 'pto' ? 'Time Off Requests' : 'Schedule Changes'}
              </Text>
            </TouchableOpacity>
          ))}
        </View>

        {subTab === 'pto'
          ? <PTOHistory list={ptoList} onCancel={cancelPTO} c={c} />
          : <SCRHistory list={scrList} c={c} onNew={() => setScrModal(true)} />
        }
      </ScrollView>

      {/* ── PTO Request Modal ── */}
      <Modal visible={ptoModal} transparent animationType="slide" onRequestClose={() => setPtoModal(false)}>
        <View style={s.modalOverlay}>
          <View style={[s.modalCard, { backgroundColor: c.card }]}>
            <Text style={[s.modalTitle, { color: c.foreground }]}>Request Time Off</Text>
            <Text style={[s.modalDate, { color: c.primary }]}>{formatFullDate(selectedDate)}</Text>
            <Text style={[s.modalBody, { color: c.mutedForeground }]}>
              This will send a PTO request to management for approval.
            </Text>
            <View style={s.modalBtns}>
              <TouchableOpacity style={[s.modalBtn, { borderColor: c.border }]} onPress={() => setPtoModal(false)}>
                <Text style={[s.modalBtnText, { color: c.foreground }]}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.modalBtn, { backgroundColor: c.primary, borderColor: c.primary, opacity: ptoSubmitting ? 0.6 : 1 }]}
                onPress={submitPTO} disabled={ptoSubmitting}
              >
                {ptoSubmitting
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={[s.modalBtnText, { color: '#fff' }]}>Submit</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* ── SCR Modal ── */}
      <Modal visible={scrModal} transparent animationType="slide" onRequestClose={() => setScrModal(false)}>
        <View style={s.modalOverlay}>
          <ScrollView style={{ width: '100%' }} contentContainerStyle={{ alignItems: 'center', paddingVertical: spacing.xl }}>
            <View style={[s.modalCard, { backgroundColor: c.card, width: '90%' }]}>
              <Text style={[s.modalTitle, { color: c.foreground }]}>Request Schedule Change</Text>

              <Text style={[s.label, { color: c.foreground }]}>Change Type</Text>
              <View style={s.chipRow}>
                {(['add_day', 'drop_day', 'full_rework'] as const).map(t => (
                  <TouchableOpacity
                    key={t}
                    style={[s.chip, scrType === t && { backgroundColor: c.primary, borderColor: c.primary }]}
                    onPress={() => setScrType(t)}
                  >
                    <Text style={[s.chipText, { color: scrType === t ? '#fff' : c.foreground }]}>{SCR_TYPE_LABELS[t]}</Text>
                  </TouchableOpacity>
                ))}
              </View>

              {scrType === 'add_day' && (
                <><Text style={[s.label, { color: c.foreground }]}>Days to Add</Text>
                <DayPicker selected={scrDaysAdd} onToggle={d => toggleDay(d, scrDaysAdd, setScrDaysAdd)} c={c} /></>
              )}
              {scrType === 'drop_day' && (
                <><Text style={[s.label, { color: c.foreground }]}>Days to Drop</Text>
                <DayPicker selected={scrDaysDrop} onToggle={d => toggleDay(d, scrDaysDrop, setScrDaysDrop)} c={c} /></>
              )}
              {scrType === 'full_rework' && (
                <><Text style={[s.label, { color: c.foreground }]}>Proposed Schedule</Text>
                <DayPicker selected={scrProposed} onToggle={d => toggleDay(d, scrProposed, setScrProposed)} c={c} /></>
              )}

              <Text style={[s.label, { color: c.foreground }]}>Reason (optional)</Text>
              <TextInput
                style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
                value={scrReason} onChangeText={setScrReason}
                placeholder="Explain your request…" placeholderTextColor={c.mutedForeground}
                multiline numberOfLines={3} textAlignVertical="top" maxLength={500}
              />
              <View style={s.modalBtns}>
                <TouchableOpacity style={[s.modalBtn, { borderColor: c.border }]} onPress={() => setScrModal(false)}>
                  <Text style={[s.modalBtnText, { color: c.foreground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[s.modalBtn, { backgroundColor: c.primary, borderColor: c.primary, opacity: scrSubmitting ? 0.6 : 1 }]}
                  onPress={submitSCR} disabled={scrSubmitting}
                >
                  {scrSubmitting ? <ActivityIndicator color="#fff" /> : <Text style={[s.modalBtnText, { color: '#fff' }]}>Submit</Text>}
                </TouchableOpacity>
              </View>
            </View>
          </ScrollView>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// ── Selected day detail card ──────────────────────────────────────────────────
function SelectedDayCard({ entry, dateStr, c }: { entry: ScheduleEntry; dateStr: string; c: ThemeColors }) {
  const s = styles(c);
  const isOff     = OFF_STATUSES.has(entry.status);
  const isWorking = !isOff;

  return (
    <View style={[s.selectedCard, { backgroundColor: c.card, borderColor: c.border }]}>
      <Text style={[s.selectedDateLabel, { color: c.foreground }]}>{formatFullDate(dateStr)}</Text>

      <View style={[s.statusPill, {
        backgroundColor: isWorking ? c.success + '18' : c.danger + '15',
      }]}>
        <Text style={[s.statusPillText, { color: isWorking ? c.success : c.danger }]}>
          {isWorking ? entry.status : entry.status}
        </Text>
      </View>

      {/* Crew roster intentionally omitted here — the live crew + AP status lives
          on the Anchor Point tab (ADR-207); showing it here duplicated that. */}
      {isWorking && entry.truck_name && (
        <View style={s.truckRow}>
          <Text style={s.truckIcon}>🚚</Text>
          <Text style={[s.truckName, { color: c.foreground }]}>Assigned to: {entry.truck_name}</Text>
        </View>
      )}

      {isWorking && !entry.truck_name && (
        <Text style={[s.selectedEmpty, { color: c.mutedForeground }]}>Assignment not yet dispatched</Text>
      )}
    </View>
  );
}

// ── PTO History ───────────────────────────────────────────────────────────────
function PTOHistory({ list, onCancel, c }: { list: PTORequest[]; onCancel: (id: string) => void; c: ThemeColors }) {
  const s = styles(c);
  if (list.length === 0) {
    return <View style={s.emptyCard}><Text style={s.emptyText}>No time-off requests yet</Text></View>;
  }
  return (
    <View style={[s.listGroup, { backgroundColor: c.card, borderColor: c.border }]}>
      {list.map((p, i) => (
        <View key={p.id} style={[s.listRow, i < list.length - 1 && { borderBottomWidth: 1, borderBottomColor: c.border }]}>
          <View style={{ flex: 1 }}>
            <Text style={[s.reqDate, { color: c.foreground }]}>{formatFullDate(p.date)}</Text>
            <View style={[s.statusBadge, { backgroundColor: statusColor(p.status, c) + '20', marginTop: 4 }]}>
              <Text style={[s.statusText, { color: statusColor(p.status, c) }]}>{p.status}</Text>
            </View>
          </View>
          {p.status === 'pending' && (
            <TouchableOpacity onPress={() => onCancel(p.id)} style={[s.cancelBtn, { borderColor: c.danger }]}>
              <Text style={[s.cancelText, { color: c.danger }]}>Cancel</Text>
            </TouchableOpacity>
          )}
        </View>
      ))}
    </View>
  );
}

// ── SCR History ───────────────────────────────────────────────────────────────
function SCRHistory({ list, c, onNew }: { list: SCR[]; c: ThemeColors; onNew: () => void }) {
  const s = styles(c);
  return (
    <>
      <TouchableOpacity style={[s.newBtn, { backgroundColor: c.primary }]} onPress={onNew}>
        <Text style={s.newBtnText}>+ New Schedule Change Request</Text>
      </TouchableOpacity>
      {list.length === 0 ? (
        <View style={s.emptyCard}><Text style={s.emptyText}>No schedule change requests</Text></View>
      ) : (
        <View style={[s.listGroup, { backgroundColor: c.card, borderColor: c.border }]}>
          {list.map((r, i) => (
            <View key={r.id} style={[s.listRow, i < list.length - 1 && { borderBottomWidth: 1, borderBottomColor: c.border }]}>
              <View style={{ flex: 1, gap: 3 }}>
                <Text style={[s.reqDate, { color: c.foreground }]}>{SCR_TYPE_LABELS[r.request_type]}</Text>
                <Text style={[s.reqMeta, { color: c.mutedForeground }]}>{r.created_at.split('T')[0]}</Text>
                {r.days_to_add.length > 0   && <Text style={[s.reqMeta, { color: c.mutedForeground }]}>Add: {r.days_to_add.join(', ')}</Text>}
                {r.days_to_drop.length > 0  && <Text style={[s.reqMeta, { color: c.mutedForeground }]}>Drop: {r.days_to_drop.join(', ')}</Text>}
                {r.proposed_schedule?.length ? <Text style={[s.reqMeta, { color: c.mutedForeground }]}>Proposed: {r.proposed_schedule.join(', ')}</Text> : null}
                {r.reason && <Text style={[s.reqMeta, { color: c.mutedForeground, fontStyle: 'italic' }]}>{r.reason}</Text>}
              </View>
              <View style={[s.statusBadge, { backgroundColor: statusColor(r.status, c) + '20' }]}>
                <Text style={[s.statusText, { color: statusColor(r.status, c) }]}>{r.status}</Text>
              </View>
            </View>
          ))}
        </View>
      )}
    </>
  );
}

// ── Day picker ────────────────────────────────────────────────────────────────
function DayPicker({ selected, onToggle, c }: { selected: string[]; onToggle: (d: string) => void; c: ThemeColors }) {
  return (
    <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginBottom: spacing.sm }}>
      {WEEKDAYS.map(day => {
        const on = selected.includes(day);
        return (
          <TouchableOpacity
            key={day}
            style={{ paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, borderRadius: radius.full, borderWidth: 1, borderColor: on ? c.primary : c.border, backgroundColor: on ? c.primary : c.card }}
            onPress={() => onToggle(day)}
          >
            <Text style={{ fontSize: fontSize.xs, color: on ? '#fff' : c.foreground, fontWeight: on ? fontWeight.semibold : fontWeight.regular }}>
              {day.slice(0, 3)}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function buildWeeks(firstDay: number, daysInMonth: number): (number | null)[][] {
  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  const weeks: (number | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) {
    const week = cells.slice(i, i + 7);
    while (week.length < 7) week.push(null);
    weeks.push(week);
  }
  return weeks;
}

// ── Styles ────────────────────────────────────────────────────────────────────
const styles = (c: ThemeColors) => StyleSheet.create({
  safe:        { flex: 1, backgroundColor: c.background },
  header:      { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.sm, borderBottomWidth: 1, borderBottomColor: c.border, backgroundColor: c.background },
  pageTitle:   { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  pageSubtitle:{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 1 },
  scroll:      { flex: 1 },
  content:     { padding: spacing.md, paddingBottom: 80 },

  monthNav:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: spacing.sm },
  navBtn:      { padding: spacing.xs },
  navArrow:    { fontSize: fontSize.xl, fontWeight: fontWeight.bold },
  monthLabel:  { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground },

  calCard:     { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.sm, marginBottom: spacing.md },
  gridRow:     { flexDirection: 'row' },
  gridCell:    { flex: 1, alignItems: 'center', paddingVertical: 4 },
  dayHeader:   { fontSize: 10, fontWeight: fontWeight.semibold, color: c.mutedForeground, paddingVertical: 4 },
  dayCircle:   { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  dateText:    { fontSize: 13, color: c.foreground },

  legend:      { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md, marginBottom: spacing.sm },
  legendItem:  { flexDirection: 'row', alignItems: 'center', gap: 5 },
  legendDot:   { width: 8, height: 8, borderRadius: 4 },
  legendText:  { fontSize: fontSize.xs, color: c.mutedForeground },

  hint:        { fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: spacing.md, fontStyle: 'italic' },

  // Selected day card
  selectedCard:    { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.md },
  selectedDateLabel:{ fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, marginBottom: spacing.xs },
  statusPill:      { alignSelf: 'flex-start', paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full, marginBottom: spacing.sm },
  statusPillText:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  truckRow:        { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.sm },
  truckIcon:       { fontSize: 16 },
  truckName:       { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  selectedEmpty:   { fontSize: fontSize.sm, marginTop: spacing.xs },

  subTabBar:        { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: c.border, marginBottom: spacing.md },
  subTab:           { flex: 1, paddingVertical: spacing.sm, alignItems: 'center' },
  subTabActive:     { borderBottomWidth: 2, borderBottomColor: c.primary },
  subTabText:       { fontSize: fontSize.xs, color: c.mutedForeground, fontWeight: fontWeight.medium },

  listGroup:   { borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden', marginBottom: spacing.sm },
  listRow:     { padding: spacing.md, flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  reqDate:     { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  reqMeta:     { fontSize: fontSize.xs },
  statusBadge: { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full, alignSelf: 'flex-start' },
  statusText:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  cancelBtn:   { borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  cancelText:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  emptyCard:   { backgroundColor: c.surfaceMuted, borderRadius: radius.lg, padding: spacing.xl, alignItems: 'center', marginBottom: spacing.sm },
  emptyText:   { fontSize: fontSize.sm, color: c.mutedForeground },
  newBtn:      { borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center', marginBottom: spacing.md },
  newBtnText:  { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'center', alignItems: 'center' },
  modalCard:    { width: '85%', borderRadius: radius.xl, padding: spacing.lg, gap: spacing.sm },
  modalTitle:   { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  modalDate:    { fontSize: fontSize.md, fontWeight: fontWeight.semibold },
  modalBody:    { fontSize: fontSize.sm, lineHeight: 20 },
  modalBtns:    { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  modalBtn:     { flex: 1, borderWidth: 1, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center' },
  modalBtnText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  label:        { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.6, marginTop: spacing.sm, marginBottom: spacing.xs },
  chipRow:      { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, marginBottom: spacing.xs },
  chip:         { paddingHorizontal: spacing.md, paddingVertical: spacing.xs, borderRadius: radius.full, borderWidth: 1, borderColor: c.border, backgroundColor: c.card },
  chipText:     { fontSize: fontSize.xs },
  textArea:     { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, fontSize: fontSize.sm, minHeight: 80, marginBottom: spacing.sm },
});
