import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useAuth } from '@contexts/AuthContext';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type Task = {
  id: string;
  topic_title: string;
  description?: string;
  is_training_debt?: boolean;
  is_completed: boolean;
  is_escalated?: boolean;
};

type Session = {
  record_id: string;
  trainee_id: string;
  trainee_name: string;
  day_number: number;
  phase: number;
  tasks: Task[];
  prev_handoff: string | null;
  manager_comments: string | null;
  handoff_notes: string | null;
  is_locked: boolean;
  submitted_at: string | null;
};

type ContinuationRequest = {
  id: string;
  trainee_id: string;
  trainee_name?: string | null;
};

export default function TrainerTodayScreen() {
  const c = useColors();
  const { user } = useAuth();
  const { fetchId } = useEmployeeId();

  const [continuations, setContinuations] = useState<ContinuationRequest[]>([]);
  const [continuationBusy, setContinuationBusy] = useState<string | null>(null);

  const loadContinuations = useCallback(async () => {
    try {
      const eid = await fetchId();
      if (!eid) return;
      const res = await apiClient.get(`/continuation-requests/trainer/${eid}`);
      const pending: ContinuationRequest[] = (res.data ?? []).filter((r: any) => r.status === 'pending');
      // Response carries ids only — resolve trainee names for display.
      const named = await Promise.all(pending.map(async r => {
        try {
          const emp = await apiClient.get(`/employees/${r.trainee_id}`);
          return { ...r, trainee_name: emp.data?.name ?? null };
        } catch { return r; }
      }));
      setContinuations(named);
    } catch { /* card is best-effort */ }
  }, [fetchId]);

  useEffect(() => { loadContinuations(); }, [loadContinuations]);

  const respondContinuation = async (req: ContinuationRequest, action: 'accept' | 'reject') => {
    setContinuationBusy(req.id);
    try {
      await apiClient.patch(`/continuation-requests/${req.id}/${action}`);
      setContinuations(prev => prev.filter(r => r.id !== req.id));
    } catch (e) {
      Alert.alert('Error', errorText(e, `Could not ${action} the request.`));
    } finally {
      setContinuationBusy(null);
    }
  };

  const [session,      setSession]      = useState<Session | null>(null);
  const [loading,      setLoading]      = useState(true);
  const [refreshing,   setRefreshing]   = useState(false);
  const [completing,   setCompleting]   = useState<string | null>(null);
  const [handoff,      setHandoff]      = useState('');
  const [savingNote,   setSavingNote]   = useState(false);
  const [completedIds, setCompletedIds] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get('/training/trainer/today');
      const data = res.data;
      if (!data.record) { setSession(null); return; }

      const record  = data.record;
      const trainee = data.trainee;
      const tasks: Task[] = data.tasks ?? [];

      setSession({
        record_id:       record.id,
        trainee_id:      trainee?.id ?? record.trainee_id,
        trainee_name:    trainee?.name ?? 'Unknown',
        day_number:      record.current_day_number,
        phase:           record.current_day_number,
        tasks,
        prev_handoff:    data.previous_trainer_comments?.comments ?? null,
        manager_comments: record.manager_comments ?? null,
        handoff_notes:   record.trainer_comments ?? null,
        is_locked:       record.is_locked ?? false,
        submitted_at:    record.submitted_at ?? null,
      });
      // Input starts EMPTY: the existing note renders in the "Already on file"
      // block, and the backend APPENDS comments — pre-filling the input with
      // the saved note would duplicate it on the next save/submit.
      setHandoff('');
      setCompletedIds(new Set(tasks.filter((t: Task) => t.is_completed).map((t: Task) => t.id)));
    } catch {
      setSession(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleTask = useCallback(async (taskId: string) => {
    if (!session) return;
    setCompleting(taskId);
    const nowDone = !completedIds.has(taskId);
    try {
      await apiClient.patch(`/training/task/${taskId}`, { is_completed: nowDone });
      setCompletedIds(prev => {
        const next = new Set(prev);
        nowDone ? next.add(taskId) : next.delete(taskId);
        return next;
      });
    } catch {
      Alert.alert('Error', 'Could not update task. Try again.');
    } finally {
      setCompleting(null);
    }
  }, [session, completedIds]);

  const [noteSaved,    setNoteSaved]    = useState(false);
  const [submitting,   setSubmitting]   = useState(false);
  const [phase4Result, setPhase4Result] = useState<{ score: number; passed: boolean } | null>(null);

  const saveHandoff = useCallback(async () => {
    if (!session || !handoff.trim()) return;
    setSavingNote(true);
    try {
      await apiClient.post(`/training/trainee/${session.trainee_id}/trainer-comments`, { comments: handoff });
      setNoteSaved(true);
      setHandoff('');
      setTimeout(() => setNoteSaved(false), 2500);
      load();   // pull the merged note back (server appends "[Added later]")
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not save note. Try again.'));
    } finally {
      setSavingNote(false);
    }
  }, [session, handoff, load]);

  const doSubmit = useCallback(async () => {
    if (!session) return;
    setSubmitting(true);
    try {
      // Persist the note first so the handoff and submission land together.
      const noteChanged = handoff.trim() && handoff.trim() !== (session.handoff_notes ?? '').trim();
      if (noteChanged) {
        await apiClient.post(`/training/trainee/${session.trainee_id}/trainer-comments`, { comments: handoff });
      }
      const res = await apiClient.post(`/training/record/${session.record_id}/submit`);
      setSession(prev => prev ? {
        ...prev,
        submitted_at: res.data.submitted_at,
        handoff_notes: noteChanged ? handoff : prev.handoff_notes,
      } : prev);
      if (res.data.phase === 4 && typeof res.data.score === 'number') {
        setPhase4Result({ score: res.data.score, passed: !!res.data.passed });
      }
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not submit the day. Try again.'));
    } finally {
      setSubmitting(false);
    }
  }, [session, handoff]);

  const submitDay = useCallback(() => {
    if (!session) return;
    const remaining = session.tasks.length - session.tasks.filter(t => completedIds.has(t.id)).length;
    if (remaining > 0) {
      Alert.alert(
        'Incomplete tasks',
        `${remaining} task${remaining === 1 ? ' is' : 's are'} still unchecked — they will carry over to ${session.trainee_name.split(' ')[0]}'s next session as training debt.`,
        [
          { text: 'Keep working', style: 'cancel' },
          { text: 'Submit anyway', style: 'destructive', onPress: doSubmit },
        ],
      );
    } else {
      doSubmit();
    }
  }, [session, completedIds, doSubmit]);

  const s = styles(c);

  if (!loading && !session) {
    return (
      <ScreenShell noHeader>
        <EmptyState c={c} />
      </ScreenShell>
    );
  }

  const debtTasks    = session?.tasks.filter(t => t.is_training_debt) ?? [];
  const currentTasks = session?.tasks.filter(t => !t.is_training_debt) ?? [];
  const doneCount    = session?.tasks.filter(t => completedIds.has(t.id)).length ?? 0;
  const totalCount   = session?.tasks.length ?? 0;
  const progress     = totalCount > 0 ? doneCount / totalCount : 0;

  return (
    <ScreenShell
      noHeader
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => { setRefreshing(true); load(); }}
    >
      {/* Hero card */}
      {session && (
        <View style={s.heroCard}>
          <View style={s.heroTop}>
            <View style={s.heroAvatar}>
              <Text style={s.heroAvatarText}>
                {session.trainee_name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
              </Text>
            </View>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Text style={s.heroLabel}>TRAINEE</Text>
                {session.is_locked && (
                  <View style={[s.lockedBadge, { backgroundColor: c.warning + '22' }]}>
                    <Text style={[s.lockedText, { color: c.warning }]}>🔒 Locked</Text>
                  </View>
                )}
                {session.submitted_at && (
                  <View style={[s.lockedBadge, { backgroundColor: c.success + '22' }]}>
                    <Text style={[s.lockedText, { color: c.success }]}>✓ Submitted</Text>
                  </View>
                )}
              </View>
              <Text style={s.heroName}>{session.trainee_name}</Text>
            </View>
            <View style={s.progressCircle}>
              <Text style={s.progressNum}>{doneCount}</Text>
              <Text style={s.progressDen}>/{totalCount}</Text>
            </View>
          </View>
          <View style={s.progressBarTrack}>
            <View style={[s.progressBarFill, { width: `${Math.round(progress * 100)}%` as any, backgroundColor: progress === 1 ? c.success : c.primary }]} />
          </View>
          <Text style={s.progressCaption}>{Math.round(progress * 100)}% complete</Text>
        </View>
      )}

      {/* Continuation requests — trainees asking to keep this trainer (ADR-012).
          Accept boosts the pairing; Decline silently releases it. */}
      {continuations.length > 0 && (
        <View style={[s.bannerCard, { borderLeftColor: c.success, backgroundColor: c.success + '10' }]}>
          <Text style={[s.bannerLabel, { color: c.success }]}>Continuation Requests</Text>
          {continuations.map(req => (
            <View key={req.id} style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xs }}>
              <Text style={[s.bannerText, { color: c.foreground, flex: 1 }]}>
                🤝 {req.trainee_name ?? 'A trainee'} wants to keep training with you
              </Text>
              <TouchableOpacity
                style={{ backgroundColor: c.success, borderRadius: radius.md, paddingHorizontal: spacing.sm + 2, paddingVertical: spacing.xs + 1 }}
                onPress={() => respondContinuation(req, 'accept')}
                disabled={continuationBusy === req.id}
              >
                <Text style={{ color: c.primaryForeground, fontSize: fontSize.xs, fontWeight: fontWeight.bold }}>Accept</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={{ borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: spacing.sm + 2, paddingVertical: spacing.xs + 1 }}
                onPress={() => respondContinuation(req, 'reject')}
                disabled={continuationBusy === req.id}
              >
                <Text style={{ color: c.mutedForeground, fontSize: fontSize.xs, fontWeight: fontWeight.semibold }}>Decline</Text>
              </TouchableOpacity>
            </View>
          ))}
        </View>
      )}

      {/* Manager directives */}
      {session?.manager_comments && (
        <View style={[s.bannerCard, { borderLeftColor: c.info, backgroundColor: c.info + '12' }]}>
          <Text style={[s.bannerLabel, { color: c.info }]}>Manager Directive</Text>
          <Text style={[s.bannerText, { color: c.foreground }]}>{session.manager_comments}</Text>
        </View>
      )}

      {/* Previous trainer notes */}
      {session?.prev_handoff && (
        <View style={[s.bannerCard, { borderLeftColor: c.primary, backgroundColor: c.primaryLight }]}>
          <Text style={[s.bannerLabel, { color: c.primary }]}>Previous Trainer's Notes</Text>
          <Text style={[s.bannerText, { color: c.foreground }]}>{session.prev_handoff}</Text>
        </View>
      )}

      {/* Carry-over tasks */}
      {debtTasks.length > 0 && (
        <TaskGroup
          label="Carry-over Tasks"
          accentColor={c.danger}
          tasks={debtTasks}
          completedIds={completedIds}
          completing={completing}
          onToggle={session?.is_locked ? () => {} : toggleTask}
          c={c}
          debt
          readOnly={session?.is_locked}
        />
      )}

      {/* Today's tasks */}
      {currentTasks.length > 0 && (
        <TaskGroup
          label="Today's Tasks"
          accentColor={c.primary}
          tasks={currentTasks}
          completedIds={completedIds}
          completing={completing}
          onToggle={session?.is_locked ? () => {} : toggleTask}
          c={c}
          readOnly={session?.is_locked}
        />
      )}

      {/* ── Complete & hand off — the day's terminal action ──────────────────
          States: in-progress (readiness chip + note + submit) → submitted
          (success card below). Submitting also persists the note, so one tap
          finishes the day. */}
      {session && !session.is_locked && !session.submitted_at && (
        <View style={[s.handoffCard, { borderColor: progress === 1 ? c.success + '66' : c.border, backgroundColor: c.card }]}>
          <View style={s.handoffHeader}>
            <Text style={s.handoffTitle}>Complete Day {session.day_number}</Text>
            <View style={[s.readyChip, { backgroundColor: progress === 1 ? c.success + '1E' : c.warning + '1E' }]}>
              <Text style={[s.readyChipText, { color: progress === 1 ? c.success : c.warning }]}>
                {progress === 1 ? '✓ All tasks done' : `${totalCount - doneCount} task${totalCount - doneCount === 1 ? '' : 's'} remaining`}
              </Text>
            </View>
          </View>
          <Text style={s.sectionHint}>
            Your handoff note is visible to the next trainer and management.
          </Text>

          {session.handoff_notes && (
            <View style={[s.existingNote, { backgroundColor: c.primaryLight }]}>
              <Text style={[s.existingNoteLabel, { color: c.primary }]}>Already on file</Text>
              <Text style={[s.existingNoteText, { color: c.foreground }]}>{session.handoff_notes}</Text>
            </View>
          )}

          <TextInput
            style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
            value={handoff}
            onChangeText={setHandoff}
            placeholder={session.handoff_notes ? 'Append additional notes…' : `How did ${session.trainee_name.split(' ')[0]} do today?`}
            placeholderTextColor={c.mutedForeground}
            multiline
            numberOfLines={4}
            textAlignVertical="top"
          />

          <TouchableOpacity
            style={[s.btn, {
              backgroundColor: progress === 1 ? c.success : c.primary,
              opacity: submitting ? 0.6 : 1,
              marginBottom: spacing.sm,
            }]}
            onPress={submitDay}
            disabled={submitting || savingNote}
          >
            {submitting
              ? <ActivityIndicator color="#fff" />
              : <Text style={s.btnText}>Submit Day {session.day_number} & Hand Off</Text>
            }
          </TouchableOpacity>

          <TouchableOpacity
            style={s.ghostBtn}
            onPress={saveHandoff}
            disabled={savingNote || submitting || !handoff.trim()}
          >
            {savingNote
              ? <ActivityIndicator size="small" color={c.mutedForeground} />
              : <Text style={[s.ghostBtnText, { color: noteSaved ? c.success : c.mutedForeground }]}>
                  {noteSaved ? '✓ Note saved' : 'Save note only — keep working'}
                </Text>
            }
          </TouchableOpacity>
        </View>
      )}

      {/* ── Submitted — success state replaces the form ── */}
      {session && session.submitted_at && (
        <View style={[s.doneCard, { backgroundColor: c.success + '11', borderColor: c.success + '55' }]}>
          <Text style={s.doneCheck}>✓</Text>
          <Text style={[s.doneTitle, { color: c.foreground }]}>Day {session.day_number} submitted</Text>
          <Text style={[s.doneSub, { color: c.mutedForeground }]}>
            {new Date(session.submitted_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
            {' · '}the next trainer and management can now see your handoff.
          </Text>
          {phase4Result && (
            <View style={[s.p4Banner, { backgroundColor: (phase4Result.passed ? c.success : c.danger) + '1E' }]}>
              <Text style={[s.p4Text, { color: phase4Result.passed ? c.success : c.danger }]}>
                Phase 4 {phase4Result.passed ? 'PASSED' : 'NOT PASSED'} · score {Math.round(phase4Result.score * 100)}%
                {!phase4Result.passed ? ' — a remediation session was generated' : ''}
              </Text>
            </View>
          )}
          {(session.handoff_notes || handoff.trim()) && (
            <View style={[s.existingNote, { backgroundColor: c.card, alignSelf: 'stretch', marginTop: spacing.sm, marginBottom: 0 }]}>
              <Text style={[s.existingNoteLabel, { color: c.primary }]}>Your Handoff Note</Text>
              <Text style={[s.existingNoteText, { color: c.foreground }]}>{session.handoff_notes || handoff}</Text>
            </View>
          )}

          {/* Same-day append only (ADR-046 §5): the record soft-locks at
              midnight; management reopens if needed. Appends are tagged
              "[Added later]" server-side. */}
          {!session.is_locked && (
            <View style={{ alignSelf: 'stretch', marginTop: spacing.sm }}>
              <TextInput
                style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.background, minHeight: 56, marginBottom: spacing.xs }]}
                value={handoff}
                onChangeText={setHandoff}
                placeholder="Forgot something? Append a note (until midnight)…"
                placeholderTextColor={c.mutedForeground}
                multiline
              />
              {handoff.trim() !== '' && (
                <TouchableOpacity style={s.ghostBtn} onPress={saveHandoff} disabled={savingNote}>
                  {savingNote
                    ? <ActivityIndicator size="small" color={c.mutedForeground} />
                    : <Text style={[s.ghostBtnText, { color: noteSaved ? c.success : c.primary }]}>
                        {noteSaved ? '✓ Note appended' : 'Append note'}
                      </Text>}
                </TouchableOpacity>
              )}
            </View>
          )}
        </View>
      )}

      {/* Read-only handoff note display when locked */}
      {session?.is_locked && !session.submitted_at && session.handoff_notes && (
        <View style={[s.bannerCard, { borderLeftColor: c.primary, backgroundColor: c.primaryLight }]}>
          <Text style={[s.bannerLabel, { color: c.primary }]}>Your Handoff Note</Text>
          <Text style={[s.bannerText, { color: c.foreground }]}>{session.handoff_notes}</Text>
        </View>
      )}
    </ScreenShell>
  );
}

// ── Task group (all tasks in one rounded card) ────────────────────────────────
function TaskGroup({
  label, accentColor, tasks, completedIds, completing, onToggle, c, debt, readOnly,
}: {
  label: string;
  accentColor: string;
  tasks: Task[];
  completedIds: Set<string>;
  completing: string | null;
  onToggle: (id: string) => void;
  c: ThemeColors;
  debt?: boolean;
  readOnly?: boolean;
}) {
  return (
    <View style={{ marginBottom: spacing.md }}>
      <View style={gs.sectionRow}>
        <View style={[gs.sectionDot, { backgroundColor: accentColor }]} />
        <Text style={[gs.sectionTitle, { color: c.foreground }]}>{label}</Text>
        <Text style={[gs.sectionCount, { color: c.mutedForeground }]}>{tasks.length}</Text>
      </View>
      <View style={[gs.group, { backgroundColor: c.card, borderColor: c.border }]}>
        {tasks.map((t, i) => (
          <TaskRow
            key={t.id}
            task={t}
            done={completedIds.has(t.id)}
            completing={completing === t.id}
            onToggle={onToggle}
            c={c}
            debt={debt}
            last={i === tasks.length - 1}
            readOnly={readOnly}
          />
        ))}
      </View>
    </View>
  );
}

function TaskRow({ task, done, completing, onToggle, c, debt, last, readOnly }: {
  task: Task; done: boolean; completing: boolean;
  onToggle: (id: string) => void; c: ThemeColors; debt?: boolean; last?: boolean; readOnly?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasDesc = !!task.description;

  return (
    <TouchableOpacity
      style={[gs.row, !last && { borderBottomWidth: 1, borderBottomColor: c.border }, debt && gs.debtRow]}
      onPress={() => hasDesc && setExpanded(e => !e)}
      activeOpacity={hasDesc ? 0.6 : 1}
    >
      {debt && <View style={[gs.debtAccent, { backgroundColor: c.danger }]} />}
      <TouchableOpacity
        style={[gs.check, done ? { backgroundColor: c.success, borderColor: c.success } : { borderColor: debt ? c.danger : c.border }, readOnly && { opacity: 0.5 }]}
        onPress={() => !readOnly && onToggle(task.id)}
        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        disabled={readOnly}
      >
        {completing
          ? <ActivityIndicator size="small" color={done ? c.primaryForeground : c.mutedForeground} />
          : done ? <Text style={[gs.checkMark, { color: c.primaryForeground }]}>✓</Text> : null
        }
      </TouchableOpacity>
      <View style={{ flex: 1 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Text style={[gs.taskTitle, done && gs.taskDone, { color: done ? c.mutedForeground : c.foreground, flex: 1 }]}>
            {task.topic_title}
          </Text>
          {hasDesc && (
            <Text style={{ fontSize: 11, color: c.mutedForeground }}>{expanded ? '▲' : '▼'}</Text>
          )}
        </View>
        {expanded && task.description ? (
          <Text style={[gs.taskDesc, { color: c.mutedForeground }]}>
            {task.description}
          </Text>
        ) : null}
      </View>
    </TouchableOpacity>
  );
}

function EmptyState({ c }: { c: ThemeColors }) {
  return (
    <View style={{ alignItems: 'center', marginTop: 64, gap: spacing.sm }}>
      <Text style={{ fontSize: 48 }}>📋</Text>
      <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground }}>No session today</Text>
      <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground }}>Check back after dispatch runs</Text>
    </View>
  );
}

// ── Shared group styles ───────────────────────────────────────────────────────
const gs = StyleSheet.create({
  sectionRow:   { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: spacing.xs, paddingHorizontal: 2 },
  sectionDot:   { width: 7, height: 7, borderRadius: 4 },
  sectionTitle: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.8, flex: 1 },
  sectionCount: { fontSize: fontSize.xs, fontWeight: fontWeight.medium },
  group:        { borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden' },
  row:          { flexDirection: 'row', alignItems: 'flex-start', paddingHorizontal: spacing.md, paddingVertical: 13, gap: spacing.sm },
  debtRow:      { paddingLeft: 0 },
  debtAccent:   { width: 3, alignSelf: 'stretch', marginRight: spacing.sm },
  check:        { width: 22, height: 22, borderRadius: 11, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center', marginTop: 1, flexShrink: 0 },
  checkMark:    { color: '#fff', fontSize: 12, fontWeight: '700' },
  taskTitle:    { fontSize: fontSize.sm, fontWeight: fontWeight.medium, lineHeight: 20 },
  taskDone:     { textDecorationLine: 'line-through' },
  taskDesc:     { fontSize: fontSize.xs, marginTop: 2, lineHeight: 16 },
});

// ── Screen-level styles ───────────────────────────────────────────────────────
const styles = (c: ThemeColors) => StyleSheet.create({
  heroCard:        {
    backgroundColor: c.card,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: c.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  heroTop:         { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.md },
  heroAvatar:      {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: c.primaryLight,
    alignItems: 'center', justifyContent: 'center',
  },
  heroAvatarText:  { fontSize: fontSize.sm, fontWeight: fontWeight.bold, color: c.primary },
  heroLabel:       { fontSize: fontSize.xs, color: c.mutedForeground, letterSpacing: 0.8, fontWeight: fontWeight.semibold },
  heroName:        { fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground, marginTop: 1 },
  progressCircle:  { flexDirection: 'row', alignItems: 'baseline' },
  progressNum:     { fontSize: fontSize.xl, fontWeight: fontWeight.extrabold, color: c.primary },
  progressDen:     { fontSize: fontSize.base, color: c.mutedForeground, fontWeight: fontWeight.medium },
  progressBarTrack:{ height: 4, backgroundColor: c.border, borderRadius: 2, overflow: 'hidden' },
  progressBarFill: { height: 4, borderRadius: 2 },
  progressCaption: { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: spacing.xs },

  bannerCard:    {
    borderLeftWidth: 3,
    borderRadius: radius.md,
    padding: spacing.sm + 4,
    marginBottom: spacing.sm,
  },
  bannerLabel:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 3 },
  bannerText:    { fontSize: fontSize.sm, lineHeight: 20 },

  lockedBadge:   { paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.full },
  lockedText:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  section:       { marginTop: spacing.sm },
  sectionLabel:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.foreground, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 2 },
  sectionHint:   { fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: spacing.sm },
  existingNote:  { borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.sm },
  existingNoteLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 3 },
  existingNoteText:  { fontSize: fontSize.sm, lineHeight: 20 },
  textArea:      { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, fontSize: fontSize.sm, minHeight: 96, marginBottom: spacing.sm },
  btn:           { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', marginBottom: spacing.lg },
  btnText:       { color: c.primaryForeground, fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  handoffCard:   { borderRadius: radius.lg, borderWidth: 1.5, padding: spacing.md, marginTop: spacing.sm, marginBottom: spacing.lg },
  handoffHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 2 },
  handoffTitle:  { fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground },
  readyChip:     { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full },
  readyChipText: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  ghostBtn:      { alignItems: 'center', paddingVertical: spacing.xs },
  ghostBtnText:  { fontSize: fontSize.xs, fontWeight: fontWeight.medium },

  doneCard:      { borderRadius: radius.lg, borderWidth: 1.5, padding: spacing.lg, marginTop: spacing.sm, marginBottom: spacing.lg, alignItems: 'center' },
  doneCheck:     { fontSize: 40, color: c.success, fontWeight: '700', marginBottom: spacing.xs },
  doneTitle:     { fontSize: fontSize.md, fontWeight: fontWeight.bold },
  doneSub:       { fontSize: fontSize.xs, textAlign: 'center', marginTop: 2 },
  p4Banner:      { borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, marginTop: spacing.sm },
  p4Text:        { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
});
