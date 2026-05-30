import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
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
};

export default function TrainerTodayScreen() {
  const c = useColors();
  const { user } = useAuth();

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
      });
      setHandoff(record.trainer_comments ?? '');
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

  const saveHandoff = useCallback(async () => {
    if (!session) return;
    setSavingNote(true);
    try {
      await apiClient.post(`/training/trainee/${session.trainee_id}/trainer-comments`, { comments: handoff });
      Alert.alert('Saved', 'Handoff note saved.');
    } catch {
      Alert.alert('Error', 'Could not save note. Try again.');
    } finally {
      setSavingNote(false);
    }
  }, [session, handoff]);

  const s = styles(c);

  if (!loading && !session) {
    return (
      <ScreenShell edges={[]} noHeader title="Today's Session" subtitle="No active session for today.">
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
      edges={[]}
      noHeader
      title="Today's Session"
      subtitle={session ? `Day ${session.day_number} · Phase ${session.phase}` : undefined}
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

      {/* Handoff note — hidden when locked */}
      {!session?.is_locked && (
        <View style={s.section}>
          <Text style={s.sectionLabel}>Handoff Note</Text>
          <Text style={s.sectionHint}>Visible to the next trainer and management</Text>
          {session?.handoff_notes && (
            <View style={[s.existingNote, { backgroundColor: c.primaryLight }]}>
              <Text style={[s.existingNoteLabel, { color: c.primary }]}>Already on file</Text>
              <Text style={[s.existingNoteText, { color: c.foreground }]}>{session.handoff_notes}</Text>
            </View>
          )}
          <TextInput
            style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }]}
            value={handoff}
            onChangeText={setHandoff}
            placeholder={session?.handoff_notes ? 'Append additional notes…' : 'Notes for the next trainer…'}
            placeholderTextColor={c.mutedForeground}
            multiline
            numberOfLines={4}
            textAlignVertical="top"
          />
          <TouchableOpacity
            style={[s.btn, { backgroundColor: c.primary, opacity: savingNote ? 0.6 : 1 }]}
            onPress={saveHandoff}
            disabled={savingNote}
          >
            {savingNote
              ? <ActivityIndicator color="#fff" />
              : <Text style={s.btnText}>Save Note</Text>
            }
          </TouchableOpacity>
        </View>
      )}

      {/* Read-only handoff note display when locked */}
      {session?.is_locked && session.handoff_notes && (
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
          ? <ActivityIndicator size="small" color={done ? '#fff' : c.mutedForeground} />
          : done ? <Text style={gs.checkMark}>✓</Text> : null
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
  btnText:       { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
});
