import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type Task = { id: string; topic: string; description?: string; mandatory: boolean };
type Preview = {
  score: number;
  passed: boolean;
  mandatory_passed: number;
  mandatory_total: number;
  failed_topics: string[];
};

export default function Phase4Screen() {
  const c = useColors();

  const [session,    setSession]    = useState<{ record_id: string; trainee_name: string; tasks: Task[] } | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [observed,   setObserved]   = useState<Set<string>>(new Set());
  const [notes,      setNotes]      = useState('');
  const [preview,    setPreview]    = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result,     setResult]     = useState<{ passed: boolean; message: string } | null>(null);

  const fetch = useCallback(async () => {
    try {
      const res = await apiClient.get('/training/trainer/today');
      if (res.data?.phase !== 4) { setSession(null); setLoading(false); return; }
      const traineeRes = await apiClient.get(`/training/trainee/${res.data.trainee_id}`);
      const tasks: Task[] = traineeRes.data?.current_tasks ?? [];
      setSession({ record_id: res.data.record_id, trainee_name: res.data.trainee_name, tasks });
    } catch {
      setSession(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  const toggleObserved = (id: string) =>
    setObserved(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const doPreview = useCallback(async () => {
    if (!session) return;
    setPreviewing(true);
    try {
      const res = await apiClient.post(`/training/record/${session.record_id}/phase4-observation`, {
        observed_task_ids: [...observed],
        notes,
      });
      setPreview(res.data);
    } catch {
      Alert.alert('Error', 'Could not calculate preview.');
    } finally {
      setPreviewing(false);
    }
  }, [session, observed, notes]);

  const doSubmit = useCallback(async () => {
    if (!session || !preview) return;
    Alert.alert('Confirm Submission', 'This will finalise the Phase 4 record. Continue?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Submit', style: 'destructive', onPress: async () => {
          setSubmitting(true);
          try {
            const res = await apiClient.post(`/training/record/${session.record_id}/submit`, {});
            setResult({
              passed: res.data.passed,
              message: res.data.passed
                ? `${session.trainee_name} passed Phase 4. Training complete.`
                : `${session.trainee_name} did not pass. Phase 5 remediation has been created.`,
            });
          } catch {
            Alert.alert('Error', 'Submission failed. Try again.');
          } finally {
            setSubmitting(false);
          }
        },
      },
    ]);
  }, [session, preview]);

  const s = styles(c);

  if (!loading && !session) {
    return (
      <ScreenShell edges={[]} noHeader title="Phase 4 Observation" subtitle="No active Phase 4 session today.">
        <View style={s.emptyCard}>
          <Text style={s.emptyText}>Not applicable today</Text>
          <Text style={s.emptySubtext}>This screen is only active when your trainee is in Phase 4</Text>
        </View>
      </ScreenShell>
    );
  }

  if (result) {
    return (
      <ScreenShell edges={[]} noHeader title="Observation Submitted" subtitle={session?.trainee_name}>
        <View style={[s.resultCard, { borderColor: result.passed ? c.success : c.danger, backgroundColor: (result.passed ? c.success : c.danger) + '12' }]}>
          <Text style={[s.resultTitle, { color: result.passed ? c.success : c.danger }]}>
            {result.passed ? 'PASSED' : 'DID NOT PASS'}
          </Text>
          <Text style={s.resultMsg}>{result.message}</Text>
        </View>
      </ScreenShell>
    );
  }

  const mandatory = session?.tasks.filter(t => t.mandatory) ?? [];
  const optional  = session?.tasks.filter(t => !t.mandatory) ?? [];

  return (
    <ScreenShell edges={[]} noHeader title="Phase 4 Observation" subtitle={session?.trainee_name} loading={loading}>
      <Text style={s.hint}>Tap each task the trainee demonstrated correctly.</Text>

      {mandatory.length > 0 && (
        <>
          <Text style={s.sectionTitle}>Mandatory ({observed.size}/{mandatory.length} observed)</Text>
          {mandatory.map(t => (
            <ObsRow key={t.id} task={t} observed={observed.has(t.id)} onToggle={toggleObserved} c={c} />
          ))}
        </>
      )}

      {optional.length > 0 && (
        <>
          <Text style={s.sectionTitle}>Optional</Text>
          {optional.map(t => (
            <ObsRow key={t.id} task={t} observed={observed.has(t.id)} onToggle={toggleObserved} c={c} />
          ))}
        </>
      )}

      <Text style={s.sectionTitle}>Observation Notes</Text>
      <TextInput
        style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }]}
        value={notes}
        onChangeText={setNotes}
        placeholder="Describe what you observed…"
        placeholderTextColor={c.mutedForeground}
        multiline
        numberOfLines={4}
        textAlignVertical="top"
      />

      {/* Preview result */}
      {preview && (
        <View style={[s.previewCard, { borderColor: preview.passed ? c.success : c.danger, backgroundColor: (preview.passed ? c.success : c.danger) + '10' }]}>
          <Text style={[s.previewScore, { color: preview.passed ? c.success : c.danger }]}>
            {Math.round(preview.score * 100)}% — {preview.passed ? 'Pass' : 'Fail'}
          </Text>
          <Text style={s.previewMeta}>Mandatory: {preview.mandatory_passed}/{preview.mandatory_total}</Text>
          {preview.failed_topics.length > 0 && (
            <Text style={[s.previewFailed, { color: c.danger }]}>Failed: {preview.failed_topics.join(', ')}</Text>
          )}
        </View>
      )}

      <TouchableOpacity
        style={[s.btn, { backgroundColor: c.primary, opacity: previewing ? 0.6 : 1 }]}
        onPress={doPreview}
        disabled={previewing}
      >
        {previewing ? <ActivityIndicator color="#fff" /> : <Text style={s.btnText}>Preview Score</Text>}
      </TouchableOpacity>

      {preview && (
        <TouchableOpacity
          style={[s.btn, { backgroundColor: c.danger, marginTop: spacing.sm, opacity: submitting ? 0.6 : 1 }]}
          onPress={doSubmit}
          disabled={submitting}
        >
          {submitting ? <ActivityIndicator color="#fff" /> : <Text style={s.btnText}>Submit Final Record</Text>}
        </TouchableOpacity>
      )}
    </ScreenShell>
  );
}

function ObsRow({ task, observed, onToggle, c }: {
  task: Task; observed: boolean; onToggle: (id: string) => void; c: ThemeColors;
}) {
  return (
    <TouchableOpacity
      style={{ flexDirection: 'row', alignItems: 'flex-start', paddingVertical: spacing.sm, gap: spacing.sm, borderBottomWidth: 1, borderBottomColor: c.border }}
      onPress={() => onToggle(task.id)}
      activeOpacity={0.7}
    >
      <View style={{ width: 22, height: 22, borderRadius: 11, borderWidth: 1.5, borderColor: observed ? c.success : c.border, backgroundColor: observed ? c.success : 'transparent', alignItems: 'center', justifyContent: 'center', marginTop: 1 }}>
        {observed && <Text style={{ color: '#fff', fontSize: 12, fontWeight: '700' }}>✓</Text>}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ fontSize: fontSize.sm, color: c.foreground, fontWeight: fontWeight.medium }}>{task.topic}</Text>
        {task.description ? <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 }}>{task.description}</Text> : null}
      </View>
    </TouchableOpacity>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  hint:         { fontSize: fontSize.sm, color: c.mutedForeground, marginBottom: spacing.md },
  sectionTitle: { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, marginTop: spacing.lg, marginBottom: spacing.sm },
  textArea:     { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, fontSize: fontSize.sm, minHeight: 100, marginBottom: spacing.sm },
  previewCard:  { borderWidth: 1.5, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.md },
  previewScore: { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  previewMeta:  { fontSize: fontSize.sm, color: '#666', marginTop: 4 },
  previewFailed:{ fontSize: fontSize.xs, marginTop: 4 },
  btn:          { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center' },
  btnText:      { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  resultCard:   { borderWidth: 1.5, borderRadius: radius.xl, padding: spacing.xl, alignItems: 'center', marginTop: spacing.xl },
  resultTitle:  { fontSize: fontSize.xxl, fontWeight: fontWeight.extrabold, marginBottom: spacing.sm },
  resultMsg:    { fontSize: fontSize.base, textAlign: 'center', lineHeight: 24, color: '#555' },
  emptyCard:    { backgroundColor: c.surfaceMuted, borderRadius: radius.lg, padding: spacing.xl, alignItems: 'center', marginTop: spacing.xl },
  emptyText:    { fontSize: fontSize.base, fontWeight: fontWeight.medium, color: c.foreground },
  emptySubtext: { fontSize: fontSize.sm, color: c.mutedForeground, marginTop: spacing.xs, textAlign: 'center' },
});
