import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { useEmployeeId } from '@hooks/useEmployeeId';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// Backend: [{ trainee: {id, name}, sessions: [{record, tasks}] }]
type Task = {
  id: string;
  topic_title: string;
  is_completed: boolean;
  is_training_debt: boolean;
  is_escalated: boolean;
};
type Session = {
  record: {
    id: string;
    record_date: string;
    current_day_number: number;
    trainer_comments: string | null;
    manager_comments: string | null;
    trainee_comments: string | null;
    trainer_rating: number | null;
  };
  tasks: Task[];
};
type TraineeGroup = {
  trainee: { id: string; name: string } | null;
  sessions: Session[];
};

export default function TrainerHistoryScreen() {
  const c = useColors();
  const { user } = useAuth();

  const [groups,     setGroups]     = useState<TraineeGroup[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  // Which trainee group is open
  const [openGroup,  setOpenGroup]  = useState<string | null>(null);
  // Which session card is expanded within a group
  const [openSession, setOpenSession] = useState<string | null>(null);

  const { fetchId } = useEmployeeId();

  const load = useCallback(async () => {
    const eid = await fetchId();
    if (!eid) return;
    try {
      const res = await apiClient.get(`/training/trainer/${eid}/history`);
      setGroups(res.data ?? []);
    } catch {
      setGroups([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [fetchId]);

  useEffect(() => { load(); }, [load]);

  const s = styles(c);

  if (!loading && groups.length === 0) {
    return (
      <ScreenShell edges={[]} noHeader title="My History" subtitle="All past training sessions">
        <View style={s.empty}>
          <Text style={{ fontSize: 44 }}>📋</Text>
          <Text style={[s.emptyTitle, { color: c.foreground }]}>No history yet</Text>
          <Text style={[s.emptySub, { color: c.mutedForeground }]}>Completed sessions will appear here</Text>
        </View>
      </ScreenShell>
    );
  }

  return (
    <ScreenShell
      edges={[]}
      noHeader
      title="My History"
      subtitle={groups.length > 0 ? `${groups.length} trainee${groups.length !== 1 ? 's' : ''} trained` : undefined}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => { setRefreshing(true); load(); }}
    >
      {groups.map(group => {
        const traineeId = group.trainee?.id ?? 'unknown';
        const isOpen = openGroup === traineeId;
        const sessions = group.sessions ?? [];

        // Aggregate stats
        const allTasks = sessions.flatMap(s => s.tasks);
        const doneCount = allTasks.filter(t => t.is_completed).length;
        const completionPct = allTasks.length > 0 ? Math.round((doneCount / allTasks.length) * 100) : 0;
        const ratedSessions = sessions.filter(s => s.record.trainer_rating != null);
        const avgRating = ratedSessions.length > 0
          ? (ratedSessions.reduce((sum, s) => sum + (s.record.trainer_rating ?? 0), 0) / ratedSessions.length).toFixed(1)
          : null;
        const lastDate = sessions[0]?.record.record_date ?? null;

        return (
          <View key={traineeId} style={[s.groupCard, { backgroundColor: c.card, borderColor: c.border }]}>
            {/* Trainee header */}
            <TouchableOpacity
              style={s.groupHeader}
              onPress={() => {
                setOpenGroup(isOpen ? null : traineeId);
                setOpenSession(null);
              }}
              activeOpacity={0.7}
            >
              <View style={[s.avatar, { backgroundColor: c.primaryLight }]}>
                <Text style={[s.avatarText, { color: c.primary }]}>
                  {(group.trainee?.name ?? 'U').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={[s.traineeName, { color: c.foreground }]}>
                  {group.trainee?.name ?? 'Unknown Trainee'}
                </Text>
                <Text style={[s.traineeMeta, { color: c.mutedForeground }]}>
                  {sessions.length} session{sessions.length !== 1 ? 's' : ''}
                  {' · '}{completionPct}% completion
                  {avgRating ? ` · ${avgRating}★ avg` : ''}
                </Text>
                {lastDate ? (
                  <Text style={[s.traineeLastDate, { color: c.mutedForeground }]}>
                    Last: {formatDate(lastDate)}
                  </Text>
                ) : null}
              </View>
              <Text style={[s.chevron, { color: c.mutedForeground }]}>{isOpen ? '▲' : '▼'}</Text>
            </TouchableOpacity>

            {/* Session list */}
            {isOpen && (
              <View style={[s.sessionList, { borderTopColor: c.border }]}>
                {sessions.map(session => {
                  const rec       = session.record;
                  const tasks     = session.tasks ?? [];
                  const debtCount = tasks.filter(t => t.is_training_debt).length;
                  const hasEscalated = tasks.some(t => t.is_escalated && !t.is_completed);
                  const done      = tasks.filter(t => t.is_completed).length;
                  const sessOpen  = openSession === rec.id;

                  return (
                    <View key={rec.id} style={[s.sessionCard, { borderColor: c.border }]}>
                      {/* Session row */}
                      <TouchableOpacity
                        style={[s.sessionRow, { backgroundColor: c.surfaceMuted }]}
                        onPress={() => setOpenSession(sessOpen ? null : rec.id)}
                        activeOpacity={0.7}
                      >
                        <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                          {hasEscalated && (
                            <Text style={{ fontSize: 12, color: c.warning }}>⚠</Text>
                          )}
                          <Text style={[s.sessionDay, { color: c.foreground }]}>
                            Day {rec.current_day_number}
                          </Text>
                          <Text style={[s.sessionDate, { color: c.mutedForeground }]}>
                            · {formatDate(rec.record_date)}
                          </Text>
                          {debtCount > 0 && (
                            <View style={[s.debtBadge, { backgroundColor: c.danger + '18' }]}>
                              <Text style={[s.debtBadgeText, { color: c.danger }]}>{debtCount} debt</Text>
                            </View>
                          )}
                        </View>
                        <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.sm }}>
                          <Text style={[s.completionText, { color: rateColor(tasks.length > 0 ? done / tasks.length : 0, c) }]}>
                            {tasks.length > 0 ? `${done}/${tasks.length}` : '—'}
                          </Text>
                          {rec.trainer_rating != null && (
                            <Text style={[s.stars, { color: c.gold }]}>
                              {'★'.repeat(rec.trainer_rating)}{'☆'.repeat(5 - rec.trainer_rating)}
                            </Text>
                          )}
                          <Text style={[s.chevron, { color: c.mutedForeground }]}>{sessOpen ? '▲' : '▼'}</Text>
                        </View>
                      </TouchableOpacity>

                      {/* Expanded session detail */}
                      {sessOpen && (
                        <View style={[s.sessionDetail, { backgroundColor: c.card }]}>
                          {/* Task list */}
                          {tasks.length > 0 && (
                            <View style={s.taskList}>
                              {tasks.map(t => (
                                <View key={t.id} style={s.taskRow}>
                                  <Text style={{
                                    fontSize: 13,
                                    color: t.is_completed ? c.success : t.is_training_debt ? c.danger : c.mutedForeground,
                                    marginRight: 6,
                                  }}>
                                    {t.is_completed ? '✓' : '✗'}
                                  </Text>
                                  <Text style={[
                                    s.taskTitle,
                                    { color: t.is_completed ? c.mutedForeground : t.is_training_debt ? c.danger : c.foreground },
                                    t.is_completed && s.taskStrike,
                                    t.is_training_debt && { fontWeight: fontWeight.semibold },
                                  ]} numberOfLines={2}>
                                    {t.topic_title}
                                  </Text>
                                </View>
                              ))}
                            </View>
                          )}

                          {/* Your handoff note */}
                          {rec.trainer_comments && (
                            <NoteBox
                              label="Your Note"
                              text={rec.trainer_comments}
                              labelColor={c.primary}
                              bg={c.primaryLight}
                              c={c}
                            />
                          )}

                          {/* Trainee review */}
                          {rec.trainer_rating != null && (
                            <View style={[s.noteBox, { backgroundColor: c.gold + '12' }]}>
                              <Text style={[s.noteLabel, { color: c.gold }]}>Trainee Review</Text>
                              <Text style={[s.stars, { color: c.gold, fontSize: fontSize.base }]}>
                                {'★'.repeat(rec.trainer_rating)}{'☆'.repeat(5 - rec.trainer_rating)}
                              </Text>
                              {rec.trainee_comments ? (
                                <Text style={[s.noteText, { color: c.foreground }]}>{rec.trainee_comments}</Text>
                              ) : null}
                            </View>
                          )}

                          {/* Manager note */}
                          {rec.manager_comments && (
                            <NoteBox
                              label="Manager Note"
                              text={rec.manager_comments}
                              labelColor={c.info}
                              bg={c.info + '12'}
                              c={c}
                            />
                          )}
                        </View>
                      )}
                    </View>
                  );
                })}
              </View>
            )}
          </View>
        );
      })}
    </ScreenShell>
  );
}

function NoteBox({ label, text, labelColor, bg, c }: {
  label: string; text: string; labelColor: string; bg: string; c: ThemeColors;
}) {
  const s = styles(c);
  return (
    <View style={[s.noteBox, { backgroundColor: bg }]}>
      <Text style={[s.noteLabel, { color: labelColor }]}>{label}</Text>
      <Text style={[s.noteText, { color: c.foreground }]}>{text}</Text>
    </View>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso + 'T12:00:00');
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

function rateColor(rate: number, c: ThemeColors) {
  if (rate >= 0.9) return c.success;
  if (rate >= 0.6) return c.warning;
  return c.danger;
}

const styles = (c: ThemeColors) => StyleSheet.create({
  empty:         { alignItems: 'center', marginTop: 64, gap: spacing.sm },
  emptyTitle:    { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
  emptySub:      { fontSize: fontSize.sm },

  // Trainee group card
  groupCard:     { borderRadius: radius.lg, borderWidth: 1, marginBottom: spacing.md, overflow: 'hidden' },
  groupHeader:   { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.md },
  avatar:        { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  avatarText:    { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  traineeName:   { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
  traineeMeta:   { fontSize: fontSize.xs, marginTop: 2 },
  traineeLastDate:{ fontSize: fontSize.xs, marginTop: 1 },
  chevron:       { fontSize: 11 },

  // Session list
  sessionList:   { borderTopWidth: 1 },
  sessionCard:   { borderBottomWidth: 1 },
  sessionRow:    { flexDirection: 'row', alignItems: 'center', paddingHorizontal: spacing.md, paddingVertical: 10, gap: spacing.sm },
  sessionDay:    { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  sessionDate:   { fontSize: fontSize.xs },
  debtBadge:     { paddingHorizontal: 6, paddingVertical: 2, borderRadius: radius.full },
  debtBadgeText: { fontSize: 10, fontWeight: fontWeight.semibold },
  completionText:{ fontSize: fontSize.xs, fontWeight: fontWeight.bold },
  stars:         { fontSize: 11, letterSpacing: 1 },

  // Session expanded detail
  sessionDetail: { padding: spacing.md, gap: spacing.sm },
  taskList:      { gap: 6, marginBottom: spacing.xs },
  taskRow:       { flexDirection: 'row', alignItems: 'flex-start' },
  taskTitle:     { fontSize: fontSize.xs, flex: 1, lineHeight: 18 },
  taskStrike:    { textDecorationLine: 'line-through' },

  // Note boxes
  noteBox:       { borderRadius: radius.md, padding: spacing.sm, gap: 4 },
  noteLabel:     { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.7 },
  noteText:      { fontSize: fontSize.sm, lineHeight: 20 },
});
