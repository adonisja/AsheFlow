import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type Task = { id: string; topic_title: string; description?: string; is_completed: boolean; is_training_debt?: boolean };
type TodayData = {
  day_number: number;
  phase: number;
  trainer_name: string | null;
  tasks: Task[];
};

export default function TraineeTodayScreen() {
  const c = useColors();
  const { user } = useAuth();
  const { fetchId } = useEmployeeId();

  const [data,       setData]       = useState<TodayData | null>(null);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetch = useCallback(async () => {
    const eid = await fetchId();
    if (!eid) return;
    try {
      const res = await apiClient.get(`/training/trainee/${eid}`);
      const today = res.data?.[0] ?? null;
      if (!today) { setData(null); setLoading(false); setRefreshing(false); return; }
      let trainer_name: string | null = null;
      if (today.trainer_id) {
        try {
          const emp = await apiClient.get(`/employees/${today.trainer_id}`);
          trainer_name = emp.data?.name ?? null;
        } catch {}
      }
      setData({
        day_number: today.current_day_number,
        phase:      today.current_day_number,
        trainer_name,
        tasks: today.tasks ?? [],
      });
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
      <ScreenShell edges={[]} noHeader title="My Training" subtitle="No active training record today.">
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
      edges={[]}
      noHeader
      title="My Training"
      subtitle={data ? `Day ${data.day_number} · Phase ${data.phase}` : undefined}
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
  const hasDesc = !!task.description;

  return (
    <TouchableOpacity
      style={[gs.row, !last && { borderBottomWidth: 1, borderBottomColor: c.border }, debt && gs.debtRow]}
      onPress={() => hasDesc && setExpanded(e => !e)}
      activeOpacity={hasDesc ? 0.6 : 1}
    >
      {debt && <View style={[gs.debtAccent, { backgroundColor: c.danger }]} />}
      <View style={[gs.check, task.is_completed
        ? { backgroundColor: c.success, borderColor: c.success }
        : { borderColor: debt ? c.danger : c.border }
      ]}>
        {task.is_completed && <Text style={gs.checkMark}>✓</Text>}
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
});
