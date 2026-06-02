import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, ScrollView, FlatList,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ── Types ─────────────────────────────────────────────────────────────────────

type BuildingType =
  | 'mailroom' | 'receptionist' | 'walkup' | 'elevator'
  | 'biz_front' | 'biz_freight' | 'biz_security' | 'biz_loading_dock';

type Profile = {
  id: string;
  block_key: string;
  building_type: BuildingType;
  workload_class: string;
  building_type_status: string;
  raw_notes: string | null;
  submitted_by_name: string | null;
  delivery_protocol: string | null;
  submitted_at: string | null;
};

// ── Constants ─────────────────────────────────────────────────────────────────

const BUILDING_TYPES: { value: BuildingType; label: string }[] = [
  { value: 'mailroom',         label: 'Mail Room' },
  { value: 'receptionist',     label: 'Receptionist' },
  { value: 'walkup',           label: 'Walk-up' },
  { value: 'elevator',         label: 'Elevator' },
  { value: 'biz_front',        label: 'Biz Front' },
  { value: 'biz_freight',      label: 'Biz Freight' },
  { value: 'biz_security',     label: 'Biz Security' },
  { value: 'biz_loading_dock', label: 'Loading Dock' },
];

const PROTOCOL: Record<BuildingType, string> = {
  mailroom:         'Photo of packages in mail room.',
  receptionist:     "Get the receptionist's name.",
  walkup:           'Photo at front door.',
  elevator:         'Photo at front door.',
  biz_front:        'Photo at front door or get receptionist\'s name.',
  biz_freight:      'Photo at front door or get receptionist\'s name.',
  biz_security:     'Bring ID. Photo at front door.',
  biz_loading_dock: 'Photo at loading dock or get mail clerk\'s name.',
};

function statusColor(status: string, primary: string): string {
  if (status === 'locked')   return '#10B981';
  if (status === 'verified') return primary;
  if (status === 'nominated') return '#F59E0B';
  return '#9CA3AF';
}

// ── Main component ────────────────────────────────────────────────────────────

export default function LocationProfilesScreen() {
  const c = useColors();
  const s = styles(c);

  const [tab,          setTab]          = useState<'browse' | 'submit'>('browse');
  const [profiles,     setProfiles]     = useState<Profile[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [refreshing,   setRefreshing]   = useState(false);
  const [searchKey,    setSearchKey]    = useState('');

  // Submit form
  const [blockKey,     setBlockKey]     = useState('');
  const [buildingType, setBuildingType] = useState<BuildingType>('walkup');
  const [rawNotes,     setRawNotes]     = useState('');
  const [submitting,   setSubmitting]   = useState(false);

  const loadProfiles = useCallback(async (bk?: string, opts?: { refresh?: boolean }) => {
    if (opts?.refresh) setRefreshing(true); else setLoading(true);
    try {
      const params: Record<string, string> = { limit: '50' };
      if (bk?.trim()) params.block_key = bk.trim();
      const res = await apiClient.get('/location-profiles/', { params });
      setProfiles(res.data ?? []);
    } catch {
      setProfiles([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { loadProfiles(); }, [loadProfiles]);

  function handleSearch() {
    loadProfiles(searchKey);
  }

  async function handleSubmit() {
    if (!blockKey.trim()) {
      Alert.alert('Missing block key', 'Enter the block key for this address.');
      return;
    }
    setSubmitting(true);
    try {
      await apiClient.post('/location-profiles/', {
        block_key:     blockKey.trim(),
        building_type: buildingType,
        raw_notes:     rawNotes.trim() || undefined,
      });
      Alert.alert('Submitted', 'Building intelligence recorded.');
      setBlockKey('');
      setRawNotes('');
      setTab('browse');
      loadProfiles();
    } catch (err: any) {
      const status = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (status === 409) {
        Alert.alert('Already locked', detail ?? 'This profile is locked. No changes accepted.');
      } else {
        Alert.alert('Error', detail ?? 'Could not submit. Try again.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  // ── Render ──

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <View style={s.header}>
        <Text style={s.title}>Location Profiles</Text>
      </View>

      {/* Tab bar */}
      <View style={s.tabRow}>
        {(['browse', 'submit'] as const).map(t => (
          <TouchableOpacity
            key={t}
            style={[s.tabBtn, t === tab && { borderBottomColor: c.primary, borderBottomWidth: 2 }]}
            onPress={() => setTab(t)}
          >
            <Text style={[s.tabBtnText, { color: t === tab ? c.primary : c.mutedForeground }]}>
              {t === 'browse' ? '🔍 Browse' : '➕ Submit'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {tab === 'browse' ? (
        <View style={{ flex: 1 }}>
          {/* Search */}
          <View style={[s.searchRow, { borderColor: c.border }]}>
            <TextInput
              style={[s.searchInput, { color: c.foreground }]}
              placeholder="Filter by block key..."
              placeholderTextColor={c.mutedForeground}
              value={searchKey}
              onChangeText={setSearchKey}
              onSubmitEditing={handleSearch}
              returnKeyType="search"
            />
            <TouchableOpacity onPress={handleSearch} style={[s.searchBtn, { backgroundColor: c.primary }]}>
              <Text style={{ color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold }}>Search</Text>
            </TouchableOpacity>
          </View>

          {loading ? (
            <View style={s.center}>
              <ActivityIndicator size="large" color={c.primary} />
            </View>
          ) : profiles.length === 0 ? (
            <View style={s.center}>
              <Text style={{ fontSize: 36 }}>📍</Text>
              <Text style={[s.emptyText, { color: c.foreground }]}>No profiles found</Text>
              <Text style={[s.emptySub, { color: c.mutedForeground }]}>Submit the first one using the Submit tab.</Text>
            </View>
          ) : (
            <FlatList
              data={profiles}
              keyExtractor={p => p.id}
              contentContainerStyle={{ padding: spacing.md, gap: spacing.sm }}
              onRefresh={() => loadProfiles(searchKey || undefined, { refresh: true })}
              refreshing={refreshing}
              renderItem={({ item: p }) => {
                const col = statusColor(p.building_type_status, c.primary);
                const typeLabel = BUILDING_TYPES.find(b => b.value === p.building_type)?.label ?? p.building_type;
                return (
                  <View style={[s.profileCard, { backgroundColor: c.surface, borderColor: c.border, borderLeftColor: col }]}>
                    <View style={s.profileHeader}>
                      <Text style={[s.profileKey, { color: c.foreground }]} numberOfLines={1}>{p.block_key}</Text>
                      <View style={[s.badge, { backgroundColor: col + '22', borderColor: col }]}>
                        <Text style={[s.badgeText, { color: col }]}>{p.building_type_status}</Text>
                      </View>
                    </View>
                    <Text style={[s.profileType, { color: c.mutedForeground }]}>{typeLabel} · {p.workload_class}</Text>
                    {p.delivery_protocol && (
                      <Text style={[s.protocol, { color: c.primary }]}>📋 {p.delivery_protocol}</Text>
                    )}
                    {p.raw_notes && (
                      <Text style={[s.notes, { color: c.mutedForeground }]} numberOfLines={2}>
                        {p.raw_notes}
                      </Text>
                    )}
                    {p.submitted_by_name && (
                      <Text style={[s.submittedBy, { color: c.mutedForeground }]}>
                        Submitted by {p.submitted_by_name}
                        {p.submitted_at ? ` · ${new Date(p.submitted_at).toLocaleDateString()}` : ''}
                      </Text>
                    )}
                  </View>
                );
              }}
            />
          )}
        </View>
      ) : (
        /* Submit form */
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>

          <Text style={[s.label, { color: c.foreground }]}>Block Key <Text style={{ color: '#EF4444' }}>*</Text></Text>
          <TextInput
            style={[s.input, { borderColor: c.border, color: c.foreground, backgroundColor: c.surface }]}
            placeholder="e.g. W_36_St_410s_odd"
            placeholderTextColor={c.mutedForeground}
            value={blockKey}
            onChangeText={setBlockKey}
            autoCapitalize="none"
          />
          <Text style={[s.hint, { color: c.mutedForeground }]}>
            The block key appears on your manifest or dispatch sheet.
          </Text>

          <Text style={[s.label, { color: c.foreground }]}>Building Type <Text style={{ color: '#EF4444' }}>*</Text></Text>
          <View style={s.typeGrid}>
            {BUILDING_TYPES.map(bt => {
              const sel = buildingType === bt.value;
              return (
                <TouchableOpacity
                  key={bt.value}
                  style={[s.typeChip, {
                    borderColor:     sel ? c.primary : c.border,
                    backgroundColor: sel ? c.primary + '18' : c.surface,
                  }]}
                  onPress={() => setBuildingType(bt.value)}
                >
                  <Text style={[s.typeChipText, { color: sel ? c.primary : c.foreground }]}>{bt.label}</Text>
                </TouchableOpacity>
              );
            })}
          </View>

          {/* Protocol hint */}
          <View style={[s.protocolBox, { backgroundColor: c.primary + '12', borderColor: c.primary }]}>
            <Text style={[s.protocolHint, { color: c.primary }]}>
              📋 {PROTOCOL[buildingType]}
            </Text>
          </View>

          <Text style={[s.label, { color: c.foreground }]}>Notes (optional)</Text>
          <TextInput
            style={[s.input, s.notesInput, { borderColor: c.border, color: c.foreground, backgroundColor: c.surface }]}
            placeholder="Anything unusual: door codes, elevator issues, access hours..."
            placeholderTextColor={c.mutedForeground}
            multiline
            numberOfLines={4}
            value={rawNotes}
            onChangeText={setRawNotes}
          />

          <TouchableOpacity
            style={[s.submitBtn, { backgroundColor: c.primary, opacity: submitting ? 0.7 : 1 }]}
            onPress={handleSubmit}
            disabled={submitting}
            activeOpacity={0.8}
          >
            {submitting
              ? <ActivityIndicator size="small" color="#fff" />
              : <Text style={s.submitBtnText}>Submit Profile</Text>
            }
          </TouchableOpacity>

          <View style={{ height: spacing.xl }} />
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:         { flex: 1, backgroundColor: c.background },
  header:       { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.xs, borderBottomWidth: 1, borderBottomColor: c.border },
  title:        { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  center:       { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm },
  emptyText:    { fontSize: fontSize.base, fontWeight: fontWeight.semibold, marginTop: spacing.sm },
  emptySub:     { fontSize: fontSize.sm, textAlign: 'center', paddingHorizontal: spacing.xl },

  tabRow:       { flexDirection: 'row', backgroundColor: c.surface, borderBottomWidth: 1, borderBottomColor: c.border },
  tabBtn:       { flex: 1, alignItems: 'center', paddingVertical: spacing.sm, borderBottomWidth: 2, borderBottomColor: 'transparent' },
  tabBtnText:   { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  searchRow:    { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, padding: spacing.sm, borderBottomWidth: 1 },
  searchInput:  { flex: 1, fontSize: fontSize.sm, paddingVertical: spacing.xs },
  searchBtn:    { paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, borderRadius: radius.sm },

  profileCard:  { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, borderLeftWidth: 4, gap: spacing.xs },
  profileHeader:{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  profileKey:   { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, flex: 1 },
  profileType:  { fontSize: fontSize.xs },
  protocol:     { fontSize: fontSize.xs, fontWeight: fontWeight.medium },
  notes:        { fontSize: fontSize.xs, fontStyle: 'italic' },
  submittedBy:  { fontSize: fontSize.xs },
  badge:        { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.xs + 2, paddingVertical: 2 },
  badgeText:    { fontSize: 10, fontWeight: fontWeight.semibold },

  label:        { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  hint:         { fontSize: fontSize.xs, marginTop: -spacing.xs },
  input:        { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs + 2, fontSize: fontSize.sm },
  notesInput:   { minHeight: 96, textAlignVertical: 'top' },
  typeGrid:     { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  typeChip:     { borderWidth: 1, borderRadius: radius.sm, paddingHorizontal: spacing.sm, paddingVertical: spacing.xs },
  typeChipText: { fontSize: fontSize.xs, fontWeight: fontWeight.medium },
  protocolBox:  { borderWidth: 1, borderRadius: radius.sm, padding: spacing.sm },
  protocolHint: { fontSize: fontSize.sm, fontWeight: fontWeight.medium },
  submitBtn:    { borderRadius: radius.md, padding: spacing.md, alignItems: 'center' },
  submitBtnText:{ color: '#fff', fontSize: fontSize.base, fontWeight: fontWeight.bold },
});
