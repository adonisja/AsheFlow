import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Alert } from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { useLayoutTransition } from '@hooks/useLayoutTransition';

type Task = { id: string; topic_title: string; description?: string; is_completed: boolean; is_training_debt?: boolean };
type TodayData = {
  record_id: string;
  day_number: number;
  phase: number;
  trainer_id: string | null;
  trainer_name: string | null;
  trainer_rating: number | null;
  tasks: Task[];
};

export default function TraineeTodayScreen() {
  const c = useColors();
  const { user } = useAuth();
  const { fetchId, cachedId } = useEmployeeId();

  const [data,       setData]       = useState<TodayData | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [stars,      setStars]      = useState(0);
  const [ratingBusy, setRatingBusy] = useState(false);
  const [rated,      setRated]      = useState(false);
  const [continueBusy, setContinueBusy] = useState(false);
  const [continueSent, setContinueSent] = useState(false);

  const submitRating = async () => {
    if (!data || stars === 0) return;
    setRatingBusy(true);
    try {
      await apiClient.post(`/training/record/${data.record_id}/review`, {
        trainer_rating: stars,
        trainee_comments: '',
      });
      setRated(true);
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not submit your rating.'));
    } finally {
      setRatingBusy(false);
    }
  };

  const requestSameTrainer = async () => {
    if (!data?.trainer_id) return;
    setContinueBusy(true);
    try {
      const eid = cachedId.current ?? (await fetchId());
      await apiClient.post('/continuation-requests/', {
        trainee_id: eid,
        trainer_id: data.trainer_id,
      });
      setContinueSent(true);
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not send the request.'));
    } finally {
      setContinueBusy(false);
    }
  };

  const fetch = useCallback(async () => {
    const eid = await fetchId();
    if (!eid) return;
    try {
      const res = await apiClient.get(`/training/trainee/${eid}`);
      // History is ordered newest-first — but [0] may be a PREVIOUS session
      // (records are created at publish; pre-publish there is none for today).
      // Showing a stale record as "TRAINER TODAY" misled operators — only a
      // record dated today counts as today's session.
      const now = new Date();
      const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
      const today = (res.data ?? []).find((r: any) => r.record_date === todayStr) ?? null;
      if (!today) { setData(null); setLoading(false); setRefreshing(false); return; }
      let trainer_name: string | null = null;
      if (today.trainer_id) {
        try {
          const emp = await apiClient.get(`/employees/${today.trainer_id}`);
          trainer_name = emp.data?.name ?? null;
        } catch {}
      }
      setData({
        record_id:      today.id,
        day_number:     today.current_day_number,
        phase:          today.current_day_number,
        trainer_id:     today.trainer_id ?? null,
        trainer_name,
        trainer_rating: today.trainer_rating ?? null,
        tasks: today.tasks ?? [],
      });

      // Restore "request sent" across refreshes — an active (pending/accepted)
      // continuation request aimed at today's trainer means it's already sent.
      if (today.trainer_id) {
        try {
          const reqs = await apiClient.get(`/continuation-requests/trainee/${eid}/active`);
          setContinueSent((reqs.data ?? []).some((r: any) => r.trainer_id === today.trainer_id));
        } catch { /* best-effort */ }
      }
    } catch {
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [fetchId]);

  useEffect(() => { fetch(); }, [fetch]);

  if (!loading && !data) {
    return (
      <ScreenShell noHeader>
        <View style={{ alignItems: 'center', marginTop: 64, gap: spacing.sm }}>
          <Text style={{ fontSize: 48 }}>📚</Text>
          <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground }}>No training session today</Text>
          <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground }}>Check back after dispatch runs</Text>
        </View>
      </ScreenShell>
    );
  }

  const debtTasks    = data?.tasks.filter(t => t.is_training_debt)  ?? [];
  const currentTasks = data?.tasks.filter(t => !t.is_training_debt) ?? [];
  const doneCount    = data?.tasks.filter(t => t.is_completed).length ?? 0;
  const totalCount   = data?.tasks.length ?? 0;
  const progress     = totalCount > 0 ? doneCount / totalCount : 0;

  return (
    <ScreenShell
      noHeader
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => { setRefreshing(true); fetch(); }}
    >
      {/* Hero card */}
      {data && (
        <View style={s(c).heroCard}>
          <View style={s(c).heroTop}>
            <View style={s(c).heroAvatar}>
              <Text style={s(c).heroAvatarText}>
                {(data.trainer_name ?? 'TBD').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
              </Text>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={s(c).heroLabel}>TRAINER TODAY</Text>
              <Text style={s(c).heroName}>{data.trainer_name ?? 'TBD'}</Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'baseline' }}>
              <Text style={s(c).progressNum}>{doneCount}</Text>
              <Text style={s(c).progressDen}>/{totalCount}</Text>
            </View>
          </View>
          <View style={s(c).progressBarTrack}>
            <View style={[s(c).progressBarFill, { width: `${Math.round(progress * 100)}%` as any, backgroundColor: progress === 1 ? c.success : c.primary }]} />
          </View>
          <Text style={s(c).progressCaption}>{Math.round(progress * 100)}% complete</Text>
        </View>
      )}

      {/* ── Day-wrapped transition — appears the moment the trainer closes
          the last task. The natural spot for the two end-of-day actions that
          were buried before: rate today's trainer, and ask to keep them. ── */}
      {data && progress === 1 && (
        <View style={[s(c).wrapCard, { backgroundColor: c.success + '0E', borderColor: c.success + '55' }]}>
          <Text style={s(c).wrapTitle}>🎉 Day {data.day_number} complete!</Text>

          {/* Rate the trainer */}
          {(rated || data.trainer_rating) ? (
            <Text style={[s(c).wrapDone, { color: c.success }]}>
              ★ You rated {data.trainer_name?.split(' ')[0] ?? 'your trainer'} {rated ? stars : data.trainer_rating}/5 — thanks!
            </Text>
          ) : (
            <>
              <Text style={s(c).wrapQuestion}>How was {data.trainer_name?.split(' ')[0] ?? 'your trainer'} today?</Text>
              <View style={s(c).starRow}>
                {[1, 2, 3, 4, 5].map(n => (
                  <TouchableOpacity key={n} onPress={() => setStars(n)} hitSlop={{ top: 8, bottom: 8, left: 4, right: 4 }}>
                    <Text style={[s(c).star, { opacity: n <= stars ? 1 : 0.25 }]}>⭐</Text>
                  </TouchableOpacity>
                ))}
                {stars > 0 && (
                  <TouchableOpacity
                    style={[s(c).starSubmit, { backgroundColor: c.success }]}
                    onPress={submitRating}
                    disabled={ratingBusy}
                  >
                    <Text style={s(c).starSubmitText}>{ratingBusy ? '…' : 'Submit'}</Text>
                  </TouchableOpacity>
                )}
              </View>
            </>
          )}

          {/* Request the same trainer */}
          {data.trainer_id && (
            continueSent ? (
              <Text style={[s(c).wrapDone, { color: c.primary }]}>
                ✓ Request sent — dispatch will try to pair you with {data.trainer_name?.split(' ')[0]} again.
              </Text>
            ) : (
              <TouchableOpacity
                style={[s(c).continueBtn, { borderColor: c.primary + '66' }]}
                onPress={requestSameTrainer}
                disabled={continueBusy}
              >
                <Text style={[s(c).continueBtnText, { color: c.primary }]}>
                  {continueBusy ? 'Sending…' : `🤝 Request ${data.trainer_name?.split(' ')[0] ?? 'this trainer'} again`}
                </Text>
              </TouchableOpacity>
            )
          )}
        </View>
      )}

      {/* Carry-over tasks */}
      {debtTasks.length > 0 && (
        <ReadOnlyGroup
          label="Carry-over Tasks"
          accentColor={c.danger}
          tasks={debtTasks}
          c={c}
          debt
        />
      )}

      {/* Today's curriculum */}
      {currentTasks.length > 0 && (
        <>
          <ReadOnlyGroup
            label="Today's Curriculum"
            accentColor={c.primary}
            tasks={currentTasks}
            c={c}
          />
          <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginTop: -spacing.xs, marginBottom: spacing.md, paddingHorizontal: 2 }}>
            Your trainer marks tasks as completed during your session.
          </Text>
        </>
      )}
    </ScreenShell>
  );
}

function ReadOnlyGroup({ label, accentColor, tasks, c, debt }: {
  label: string; accentColor: string; tasks: Task[]; c: ThemeColors; debt?: boolean;
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
          <ReadOnlyTaskRow key={t.id} task={t} c={c} debt={debt} last={i === tasks.length - 1} />
        ))}
      </View>
    </View>
  );
}

function ReadOnlyTaskRow({ task, c, debt, last }: { task: Task; c: ThemeColors; debt?: boolean; last?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const animateNext = useLayoutTransition();
  const hasDesc = !!task.description;

  return (
    <TouchableOpacity
      style={[gs.row, !last && { borderBottomWidth: 1, borderBottomColor: c.border }, debt && gs.debtRow]}
      onPress={() => { if (hasDesc) { animateNext(); setExpanded(e => !e); } }}
      activeOpacity={hasDesc ? 0.6 : 1}
    >
      {debt && <View style={[gs.debtAccent, { backgroundColor: c.danger }]} />}
      <View style={[gs.check, task.is_completed
        ? { backgroundColor: c.success, borderColor: c.success }
        : { borderColor: debt ? c.danger : c.border }
      ]}>
        {task.is_completed && <Text style={[gs.checkMark, { color: c.primaryForeground }]}>✓</Text>}
      </View>
      <View style={{ flex: 1 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <Text style={[gs.taskTitle, task.is_completed && gs.taskDone, { color: task.is_completed ? c.mutedForeground : c.foreground, flex: 1 }]}>
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

const s = (c: ThemeColors) => StyleSheet.create({
  heroCard:        { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.md },
  heroTop:         { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.md },
  heroAvatar:      { width: 44, height: 44, borderRadius: 22, backgroundColor: c.primaryLight, alignItems: 'center', justifyContent: 'center' },
  heroAvatarText:  { fontSize: fontSize.sm, fontWeight: fontWeight.bold, color: c.primary },
  heroLabel:       { fontSize: fontSize.xs, color: c.mutedForeground, letterSpacing: 0.8, fontWeight: fontWeight.semibold },
  heroName:        { fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground, marginTop: 1 },
  progressNum:     { fontSize: fontSize.xl, fontWeight: fontWeight.extrabold, color: c.primary },
  progressDen:     { fontSize: fontSize.base, color: c.mutedForeground, fontWeight: fontWeight.medium },
  progressBarTrack:{ height: 4, backgroundColor: c.border, borderRadius: 2, overflow: 'hidden' },
  progressBarFill: { height: 4, borderRadius: 2 },
  progressCaption: { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: spacing.xs },

  wrapCard:      { borderRadius: radius.lg, borderWidth: 1.5, padding: spacing.md, marginBottom: spacing.md },
  wrapTitle:     { fontSize: fontSize.md, fontWeight: fontWeight.bold, color: c.foreground, marginBottom: spacing.xs },
  wrapQuestion:  { fontSize: fontSize.sm, color: c.foreground, marginBottom: spacing.xs },
  wrapDone:      { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, marginVertical: spacing.xs },
  starRow:       { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: spacing.sm },
  star:          { fontSize: 26 },
  starSubmit:    { marginLeft: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 2, borderRadius: radius.full },
  starSubmitText:{ color: c.primaryForeground, fontSize: fontSize.xs, fontWeight: fontWeight.bold },
  continueBtn:   { borderWidth: 1.5, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center', marginTop: spacing.xs },
  continueBtnText:{ fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
});
