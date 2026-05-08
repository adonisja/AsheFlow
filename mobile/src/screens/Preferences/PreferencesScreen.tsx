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
type Relationship = {
  id: string;
  target_employee_id: string;
  relationship_type: 'fav' | 'ban';
};

type Employee = {
  id: string;
  name: string;
  role: string;
};

type ReassignRequest = {
  id: string;
  requested_date: string;
  reason: string | null;
  status: string;
  created_at: string;
};

type WalkerRatingRow = {
  id: string;
  date: string;
  driver_name: string | null;
  present: boolean;
  stars: number | null;
  comment: string | null;
};

type WalkerProfile = {
  total_shifts: number;
  present: number;
  no_shows: number;
  avg_stars: number | null;
  presence_rate: number | null;
  grade: string | null;
  ratings: WalkerRatingRow[];
};

// ── Limits (mirrors backend FAV_LIMITS) ───────────────────────────────────────
const FAV_LIMITS: Record<string, Record<string, number>> = {
  driver:  { driver: 0, trainer: 1, walker: 2 },
  trainer: { driver: 1, trainer: 1, walker: 2 },
  walker:  { driver: 1, trainer: 1, walker: 2 },
};

function favLimitFor(myRole: string, targetRole: string): number {
  return FAV_LIMITS[myRole]?.[targetRole] ?? 0;
}

function statusColor(status: string, c: typeof lightColors) {
  if (status === 'approved') return c.success;
  if (status === 'rejected') return c.danger;
  return c.warning;
}

function gradeColor(grade: string | null, c: typeof lightColors) {
  if (grade === 'A' || grade === 'B') return c.success;
  if (grade === 'C') return c.warning;
  return c.danger;
}

// ── Main screen ───────────────────────────────────────────────────────────────
export default function PreferencesScreen() {
  const scheme = useColorScheme();
  const c = scheme === 'dark' ? darkColors : lightColors;
  const { user, hasRole } = useAuth();

  const isWalker  = hasRole('walker');
  const isTrainer = hasRole('trainer');
  const canReassign = isWalker || isTrainer;

  // Determine which sub-tabs to show
  const tabs = [
    { key: 'favban', label: 'Fav / Ban' },
    ...(canReassign ? [{ key: 'reassign', label: 'Reassignment' }] : []),
    ...(isWalker    ? [{ key: 'performance', label: 'My Performance' }] : []),
  ];
  const [activeTab, setActiveTab] = useState(tabs[0].key);

  const [employeeId, setEmployeeId] = useState<string | null>(null);
  const [myRole,     setMyRole]     = useState<string>('');
  const [loading,    setLoading]    = useState(true);

  // Fav/Ban state
  const [relationships, setRelationships] = useState<Relationship[]>([]);
  const [employees,     setEmployees]     = useState<Employee[]>([]);
  const [empMap,        setEmpMap]        = useState<Record<string, Employee>>({});
  const [filterType,    setFilterType]    = useState<'fav' | 'ban'>('fav');
  const [addModal,      setAddModal]      = useState(false);
  const [addType,       setAddType]       = useState<'fav' | 'ban'>('fav');
  const [searchQuery,   setSearchQuery]   = useState('');
  const [adding,        setAdding]        = useState(false);

  // Reassignment state
  const [reassignList,  setReassignList]  = useState<ReassignRequest[]>([]);
  const [reassignModal, setReassignModal] = useState(false);
  const [reassignReason,setReassignReason]= useState('');
  const [reassigning,   setReassigning]   = useState(false);

  // Walker performance state
  const [profile,  setProfile]  = useState<WalkerProfile | null>(null);
  const [profLoad, setProfLoad] = useState(false);

  // Resolve employee ID + role once
  useEffect(() => {
    apiClient.get('/employees/me').then(r => {
      setEmployeeId(r.data?.id ?? null);
      setMyRole(r.data?.role ?? '');
    }).catch(() => {});
  }, []);

  // Fetch all field employees for the add-relationship picker
  useEffect(() => {
    apiClient.get('/employees/?role=driver&limit=200').then(r1 =>
      apiClient.get('/employees/?role=walker&limit=200').then(r2 =>
        apiClient.get('/employees/?role=trainer&limit=200').then(r3 => {
          const all: Employee[] = [
            ...(r1.data?.items ?? r1.data ?? []),
            ...(r2.data?.items ?? r2.data ?? []),
            ...(r3.data?.items ?? r3.data ?? []),
          ];
          setEmployees(all);
          setEmpMap(Object.fromEntries(all.map(e => [e.id, e])));
        })
      )
    ).catch(() => {});
  }, []);

  const fetchRelationships = useCallback(async () => {
    if (!employeeId) return;
    try {
      const res = await apiClient.get(`/employee-relationships/${employeeId}`);
      setRelationships(res.data ?? []);
    } catch {
      setRelationships([]);
    } finally {
      setLoading(false);
    }
  }, [employeeId]);

  const fetchReassignments = useCallback(async () => {
    if (!employeeId) return;
    try {
      const res = await apiClient.get(`/assignment-change-requests/employee/${employeeId}`);
      setReassignList(res.data ?? []);
    } catch {
      setReassignList([]);
    }
  }, [employeeId]);

  const fetchProfile = useCallback(async () => {
    if (!employeeId || !isWalker) return;
    setProfLoad(true);
    try {
      const res = await apiClient.get(`/field-ops/walker-profile/${employeeId}`);
      setProfile(res.data ?? null);
    } catch {
      setProfile(null);
    } finally {
      setProfLoad(false);
    }
  }, [employeeId, isWalker]);

  useEffect(() => {
    if (employeeId) {
      fetchRelationships();
      if (canReassign) fetchReassignments();
      if (isWalker) fetchProfile();
    }
  }, [employeeId, fetchRelationships, fetchReassignments, fetchProfile, canReassign, isWalker]);

  // ── Add relationship ─────────────────────────────────────────────────────────
  const addRelationship = useCallback(async (targetId: string) => {
    if (!employeeId) return;
    setAdding(true);
    try {
      await apiClient.post('/employee-relationships/', {
        employee_id: employeeId,
        target_employee_id: targetId,
        relationship_type: addType,
      });
      setAddModal(false);
      setSearchQuery('');
      fetchRelationships();
    } catch (err: any) {
      Alert.alert('Error', err.response?.data?.detail ?? 'Could not add. Try again.');
    } finally {
      setAdding(false);
    }
  }, [employeeId, addType, fetchRelationships]);

  const removeRelationship = useCallback(async (relId: string) => {
    Alert.alert('Remove', 'Remove this relationship?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Remove', style: 'destructive',
        onPress: async () => {
          try {
            await apiClient.delete(`/employee-relationships/${relId}`);
            fetchRelationships();
          } catch {
            Alert.alert('Error', 'Could not remove.');
          }
        },
      },
    ]);
  }, [fetchRelationships]);

  // ── Submit reassignment ──────────────────────────────────────────────────────
  const submitReassign = useCallback(async () => {
    if (!employeeId) return;
    setReassigning(true);
    const today = new Date().toISOString().split('T')[0];
    try {
      await apiClient.post('/assignment-change-requests/', {
        employee_id: employeeId,
        requested_date: today,
        reason: reassignReason.trim() || undefined,
      });
      Alert.alert('Submitted', 'Dispatch has been notified of your reassignment request.');
      setReassignModal(false);
      setReassignReason('');
      fetchReassignments();
    } catch (err: any) {
      Alert.alert('Error', err.response?.data?.detail ?? 'Could not submit. Try again.');
    } finally {
      setReassigning(false);
    }
  }, [employeeId, reassignReason, fetchReassignments]);

  const cancelReassign = useCallback(async (id: string) => {
    Alert.alert('Cancel Request', 'Cancel this reassignment request?', [
      { text: 'No', style: 'cancel' },
      {
        text: 'Yes, Cancel', style: 'destructive',
        onPress: async () => {
          try {
            await apiClient.delete(`/assignment-change-requests/${id}`);
            fetchReassignments();
          } catch {
            Alert.alert('Error', 'Could not cancel.');
          }
        },
      },
    ]);
  }, [fetchReassignments]);

  const s = styles(c);

  // ── Derived for fav/ban list ─────────────────────────────────────────────────
  const filtered = relationships.filter(r => r.relationship_type === filterType);

  // Employees not already in a relationship of addType
  const existingTargets = new Set(relationships.filter(r => r.relationship_type === addType).map(r => r.target_employee_id));
  const eligible = employees.filter(e =>
    e.id !== employeeId &&
    !existingTargets.has(e.id) &&
    (addType === 'ban' || favLimitFor(myRole, e.role) > 0) &&
    (searchQuery.trim() === '' || e.name.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      {/* Sub-tab bar */}
      <View style={s.tabBar}>
        {tabs.map(t => (
          <TouchableOpacity
            key={t.key}
            style={[s.tab, activeTab === t.key && s.tabActive]}
            onPress={() => setActiveTab(t.key)}
          >
            <Text style={[s.tabText, activeTab === t.key && s.tabTextActive]}>{t.label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView style={s.scroll} contentContainerStyle={s.content}>

        {/* ── FAV / BAN TAB ────────────────────────────────────────────────── */}
        {activeTab === 'favban' && (
          <>
            <Text style={s.pageTitle}>Preferences</Text>
            <Text style={s.subtitle}>
              Your fav/ban preferences influence how dispatch assigns your crew. Only dispatch can see the effect — no one sees your list directly.
            </Text>

            {/* Type filter + Add button */}
            <View style={s.row}>
              {(['fav', 'ban'] as const).map(t => (
                <TouchableOpacity
                  key={t}
                  style={[s.filterChip, filterType === t && { backgroundColor: t === 'fav' ? c.success : c.danger, borderColor: t === 'fav' ? c.success : c.danger }]}
                  onPress={() => setFilterType(t)}
                >
                  <Text style={[s.filterChipText, filterType === t && { color: '#fff' }]}>
                    {t === 'fav' ? '★ Favorites' : '⊘ Blocked'}
                  </Text>
                </TouchableOpacity>
              ))}
              <TouchableOpacity
                style={[s.addBtn, { backgroundColor: c.primary }]}
                onPress={() => { setAddType(filterType); setAddModal(true); }}
              >
                <Text style={s.addBtnText}>+ Add</Text>
              </TouchableOpacity>
            </View>

            {/* Limit info */}
            {filterType === 'fav' && myRole && (
              <Text style={[s.hint, { color: c.mutedForeground }]}>
                {myRole === 'driver'
                  ? 'Drivers: up to 1 trainer, 2 walkers'
                  : 'Up to 1 driver, 1 trainer, 2 walkers'}
              </Text>
            )}
            {filterType === 'ban' && (
              <Text style={[s.hint, { color: c.mutedForeground }]}>
                Up to 2 active bans. Management is never notified of who you blocked.
              </Text>
            )}

            {loading ? (
              <ActivityIndicator color={c.primary} style={{ marginTop: spacing.xl }} />
            ) : filtered.length === 0 ? (
              <View style={s.emptyCard}>
                <Text style={s.emptyText}>No {filterType === 'fav' ? 'favorites' : 'blocked employees'} yet</Text>
              </View>
            ) : filtered.map(rel => {
              const emp = empMap[rel.target_employee_id];
              return (
                <View key={rel.id} style={s.relCard}>
                  <View style={[s.roleTag, { backgroundColor: c.primary + '20' }]}>
                    <Text style={[s.roleTagText, { color: c.primary }]}>{emp?.role ?? '—'}</Text>
                  </View>
                  <Text style={[s.relName, { color: c.foreground }]}>{emp?.name ?? rel.target_employee_id}</Text>
                  <TouchableOpacity onPress={() => removeRelationship(rel.id)} style={[s.removeBtn, { borderColor: c.danger }]}>
                    <Text style={[s.removeBtnText, { color: c.danger }]}>Remove</Text>
                  </TouchableOpacity>
                </View>
              );
            })}
          </>
        )}

        {/* ── REASSIGNMENT TAB ─────────────────────────────────────────────── */}
        {activeTab === 'reassign' && (
          <>
            <Text style={s.pageTitle}>Reassignment</Text>
            <Text style={s.subtitle}>
              Request to be moved to a different truck today. Dispatch will process your request and update your assignment.
            </Text>

            {/* Only allow one pending at a time — backend enforces this too */}
            {!reassignList.some(r => r.status === 'pending') && (
              <TouchableOpacity
                style={[s.primaryBtn, { backgroundColor: c.primary }]}
                onPress={() => setReassignModal(true)}
              >
                <Text style={s.primaryBtnText}>Request Reassignment for Today</Text>
              </TouchableOpacity>
            )}

            {reassignList.length === 0 ? (
              <View style={s.emptyCard}><Text style={s.emptyText}>No requests yet</Text></View>
            ) : reassignList.map(r => (
              <View key={r.id} style={s.relCard}>
                <View style={{ flex: 1, gap: 4 }}>
                  <Text style={[s.relName, { color: c.foreground }]}>{r.requested_date}</Text>
                  {r.reason && <Text style={[s.hint, { color: c.mutedForeground }]}>{r.reason}</Text>}
                  <Text style={[s.hint, { color: c.mutedForeground }]}>{r.created_at.split('T')[0]}</Text>
                </View>
                <View style={{ alignItems: 'flex-end', gap: 6 }}>
                  <View style={[s.statusBadge, { backgroundColor: statusColor(r.status, c) + '20' }]}>
                    <Text style={[s.statusText, { color: statusColor(r.status, c) }]}>{r.status}</Text>
                  </View>
                  {r.status === 'pending' && (
                    <TouchableOpacity onPress={() => cancelReassign(r.id)} style={[s.removeBtn, { borderColor: c.danger }]}>
                      <Text style={[s.removeBtnText, { color: c.danger }]}>Cancel</Text>
                    </TouchableOpacity>
                  )}
                </View>
              </View>
            ))}
          </>
        )}

        {/* ── WALKER PERFORMANCE TAB ───────────────────────────────────────── */}
        {activeTab === 'performance' && (
          <>
            <Text style={s.pageTitle}>My Performance</Text>
            <Text style={s.subtitle}>Your all-time stats as rated by your drivers.</Text>

            {profLoad ? (
              <ActivityIndicator color={c.primary} style={{ marginTop: spacing.xl }} />
            ) : !profile ? (
              <View style={s.emptyCard}><Text style={s.emptyText}>No performance data yet</Text></View>
            ) : (
              <>
                {/* Grade banner */}
                <View style={[s.gradeBanner, { backgroundColor: gradeColor(profile.grade, c) + '18', borderColor: gradeColor(profile.grade, c) + '40' }]}>
                  <Text style={[s.gradeLabel, { color: gradeColor(profile.grade, c) }]}>
                    Grade: {profile.grade ?? '—'}
                  </Text>
                  <Text style={[s.gradeHint, { color: gradeColor(profile.grade, c) }]}>
                    {profile.grade === 'A' ? 'Excellent standing' :
                     profile.grade === 'B' ? 'Good standing' :
                     profile.grade === 'C' ? 'Needs improvement' : 'At risk'}
                  </Text>
                </View>

                {/* KPI row */}
                <View style={s.kpiRow}>
                  {[
                    { label: 'Shifts',    value: String(profile.total_shifts) },
                    { label: 'Present',   value: String(profile.present) },
                    { label: 'No-Shows',  value: String(profile.no_shows) },
                    { label: 'Presence',  value: profile.presence_rate != null ? `${profile.presence_rate}%` : '—' },
                    { label: 'Avg Stars', value: profile.avg_stars != null ? `${profile.avg_stars}★` : '—' },
                  ].map(({ label, value }) => (
                    <View key={label} style={[s.kpiCard, { backgroundColor: c.card, borderColor: c.border }]}>
                      <Text style={[s.kpiValue, { color: c.foreground }]}>{value}</Text>
                      <Text style={[s.kpiLabel, { color: c.mutedForeground }]}>{label}</Text>
                    </View>
                  ))}
                </View>

                {/* Recent ratings */}
                <Text style={s.sectionLabel}>Recent Reviews</Text>
                {profile.ratings.length === 0 ? (
                  <View style={s.emptyCard}><Text style={s.emptyText}>No reviews yet</Text></View>
                ) : profile.ratings.slice(0, 20).map(r => (
                  <View key={r.id} style={[s.reviewCard, { backgroundColor: c.card, borderColor: c.border }]}>
                    <View style={s.reviewTop}>
                      <Text style={[s.reviewDate, { color: c.foreground }]}>{r.date}</Text>
                      {r.present ? (
                        <Text style={{ fontSize: fontSize.sm, color: c.gold }}>
                          {r.stars != null ? '★'.repeat(r.stars) + '☆'.repeat(5 - r.stars) : 'No rating'}
                        </Text>
                      ) : (
                        <View style={[s.absentBadge, { backgroundColor: c.danger + '20' }]}>
                          <Text style={[s.absentText, { color: c.danger }]}>Absent</Text>
                        </View>
                      )}
                    </View>
                    {r.driver_name && (
                      <Text style={[s.reviewDriver, { color: c.mutedForeground }]}>Driver: {r.driver_name}</Text>
                    )}
                    {r.comment && (
                      <Text style={[s.reviewComment, { color: c.foreground }]}>{r.comment}</Text>
                    )}
                  </View>
                ))}
              </>
            )}
          </>
        )}
      </ScrollView>

      {/* ── Add Relationship Modal ── */}
      <Modal visible={addModal} transparent animationType="slide" onRequestClose={() => setAddModal(false)}>
        <View style={s.overlay}>
          <View style={[s.modalCard, { backgroundColor: c.card }]}>
            <Text style={[s.modalTitle, { color: c.foreground }]}>
              {addType === 'fav' ? 'Add Favorite' : 'Block Employee'}
            </Text>
            {addType === 'ban' && (
              <View style={[s.warningBox, { backgroundColor: c.warning + '18', borderColor: c.warning + '40' }]}>
                <Text style={[s.warningText, { color: c.warning }]}>
                  Blocking prevents dispatch from pairing you with this person. Management cannot see who you block.
                </Text>
              </View>
            )}

            {/* Type toggle */}
            <View style={[s.row, { marginBottom: spacing.sm }]}>
              {(['fav', 'ban'] as const).map(t => (
                <TouchableOpacity
                  key={t}
                  style={[s.filterChip, addType === t && { backgroundColor: t === 'fav' ? c.success : c.danger, borderColor: t === 'fav' ? c.success : c.danger }]}
                  onPress={() => setAddType(t)}
                >
                  <Text style={[s.filterChipText, addType === t && { color: '#fff' }]}>
                    {t === 'fav' ? '★ Fav' : '⊘ Block'}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>

            <TextInput
              style={[s.searchInput, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
              value={searchQuery}
              onChangeText={setSearchQuery}
              placeholder="Search by name…"
              placeholderTextColor={c.mutedForeground}
            />

            <ScrollView style={{ maxHeight: 260 }}>
              {eligible.length === 0 ? (
                <Text style={[s.hint, { color: c.mutedForeground, padding: spacing.sm }]}>
                  {searchQuery ? 'No matches' : 'No eligible employees'}
                </Text>
              ) : eligible.map(emp => (
                <TouchableOpacity
                  key={emp.id}
                  style={[s.empRow, { borderColor: c.border }]}
                  onPress={() => addRelationship(emp.id)}
                  disabled={adding}
                >
                  <View style={[s.roleTag, { backgroundColor: c.primary + '20' }]}>
                    <Text style={[s.roleTagText, { color: c.primary }]}>{emp.role}</Text>
                  </View>
                  <Text style={[s.relName, { color: c.foreground, flex: 1 }]}>{emp.name}</Text>
                  {adding ? <ActivityIndicator size="small" color={c.primary} /> : <Text style={{ color: c.primary }}>+</Text>}
                </TouchableOpacity>
              ))}
            </ScrollView>

            <TouchableOpacity style={[s.closeBtn, { borderColor: c.border }]} onPress={() => { setAddModal(false); setSearchQuery(''); }}>
              <Text style={[s.closeBtnText, { color: c.foreground }]}>Close</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* ── Reassignment Request Modal ── */}
      <Modal visible={reassignModal} transparent animationType="slide" onRequestClose={() => setReassignModal(false)}>
        <View style={s.overlay}>
          <View style={[s.modalCard, { backgroundColor: c.card }]}>
            <Text style={[s.modalTitle, { color: c.foreground }]}>Request Reassignment</Text>
            <Text style={[s.modalBody, { color: c.mutedForeground }]}>
              This will notify dispatch to move you to a different truck for today.
            </Text>
            <Text style={[s.fieldLabel, { color: c.foreground }]}>Reason (optional)</Text>
            <TextInput
              style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
              value={reassignReason}
              onChangeText={setReassignReason}
              placeholder="Briefly explain why you need to move…"
              placeholderTextColor={c.mutedForeground}
              multiline
              numberOfLines={3}
              textAlignVertical="top"
              maxLength={300}
            />
            <View style={s.modalBtns}>
              <TouchableOpacity style={[s.modalBtn, { borderColor: c.border }]} onPress={() => setReassignModal(false)}>
                <Text style={[s.modalBtnText, { color: c.foreground }]}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[s.modalBtn, { backgroundColor: c.primary, borderColor: c.primary, opacity: reassigning ? 0.6 : 1 }]}
                onPress={submitReassign}
                disabled={reassigning}
              >
                {reassigning ? <ActivityIndicator color="#fff" /> : <Text style={[s.modalBtnText, { color: '#fff' }]}>Submit</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────
const styles = (c: typeof lightColors) => StyleSheet.create({
  safe:           { flex: 1, backgroundColor: c.background },
  scroll:         { flex: 1 },
  content:        { padding: spacing.lg, paddingBottom: spacing.xxl },
  tabBar:         { flexDirection: 'row', borderBottomWidth: 1, borderBottomColor: c.border, backgroundColor: c.surface },
  tab:            { flex: 1, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  tabActive:      { borderBottomWidth: 2, borderBottomColor: c.primary },
  tabText:        { fontSize: fontSize.xs, color: c.mutedForeground, fontWeight: fontWeight.medium },
  tabTextActive:  { color: c.primary, fontWeight: fontWeight.semibold },
  pageTitle:      { fontSize: fontSize.xxl, fontWeight: fontWeight.extrabold, color: c.foreground, marginBottom: spacing.xs },
  subtitle:       { fontSize: fontSize.sm, color: c.mutedForeground, lineHeight: 20, marginBottom: spacing.lg },
  row:            { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm },
  filterChip:     { paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, borderRadius: radius.full, borderWidth: 1, borderColor: c.border, backgroundColor: c.card },
  filterChipText: { fontSize: fontSize.sm, color: c.foreground, fontWeight: fontWeight.medium },
  addBtn:         { marginLeft: 'auto', borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2 },
  addBtnText:     { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  hint:           { fontSize: fontSize.xs, marginBottom: spacing.sm },
  relCard:        { flexDirection: 'row', alignItems: 'center', backgroundColor: c.card, borderRadius: radius.md, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.sm, gap: spacing.sm },
  roleTag:        { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  roleTagText:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  relName:        { fontSize: fontSize.sm, fontWeight: fontWeight.medium },
  removeBtn:      { borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  removeBtnText:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  emptyCard:      { backgroundColor: c.surfaceMuted, borderRadius: radius.lg, padding: spacing.xl, alignItems: 'center', marginTop: spacing.sm },
  emptyText:      { fontSize: fontSize.base, color: c.mutedForeground },
  primaryBtn:     { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', marginBottom: spacing.md },
  primaryBtnText: { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  statusBadge:    { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  statusText:     { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  // Performance
  gradeBanner:    { borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md, alignItems: 'center' },
  gradeLabel:     { fontSize: fontSize.xxl, fontWeight: fontWeight.extrabold },
  gradeHint:      { fontSize: fontSize.xs, marginTop: 2 },
  kpiRow:         { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.md },
  kpiCard:        { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, minWidth: 80, alignItems: 'center', flex: 1 },
  kpiValue:       { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  kpiLabel:       { fontSize: fontSize.xs, marginTop: 2 },
  sectionLabel:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: spacing.sm },
  reviewCard:     { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm, gap: 4 },
  reviewTop:      { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  reviewDate:     { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  reviewDriver:   { fontSize: fontSize.xs },
  reviewComment:  { fontSize: fontSize.sm, lineHeight: 20 },
  absentBadge:    { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  absentText:     { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  // Modals
  overlay:        { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'center', alignItems: 'center' },
  modalCard:      { width: '90%', borderRadius: radius.xl, padding: spacing.lg, gap: spacing.sm, maxHeight: '80%' },
  modalTitle:     { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  modalBody:      { fontSize: fontSize.sm, lineHeight: 20 },
  warningBox:     { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm },
  warningText:    { fontSize: fontSize.xs, lineHeight: 18 },
  searchInput:    { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, fontSize: fontSize.sm, marginBottom: spacing.xs },
  empRow:         { flexDirection: 'row', alignItems: 'center', borderBottomWidth: 1, paddingVertical: spacing.sm, gap: spacing.sm },
  closeBtn:       { borderWidth: 1, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center', marginTop: spacing.sm },
  closeBtnText:   { fontSize: fontSize.sm, fontWeight: fontWeight.medium },
  fieldLabel:     { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: spacing.xs },
  textArea:       { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, fontSize: fontSize.sm, minHeight: 80, marginBottom: spacing.xs },
  modalBtns:      { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.sm },
  modalBtn:       { flex: 1, borderWidth: 1, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center' },
  modalBtnText:   { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
});
