import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet,
  TextInput, Alert, ActivityIndicator,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type Record_ = {
  record_id: string;
  date: string;
  day_number: number;
  phase: number;
  trainer_name: string | null;
  task_completion_rate: number;
  review_submitted: boolean;
  review_window_open: boolean;
  stars: number | null;
  comment: string | null;
};

export default function TraineeHistoryScreen() {
  const c = useColors();
  const { user } = useAuth();

  const [records,    setRecords]    = useState<Record_[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [expanded,   setExpanded]   = useState<Set<string>>(new Set());
  const [reviewState, setReviewState] = useState<Record<string, { stars: number; comment: string; submitting: boolean }>>({});

  const fetch = useCallback(async () => {
    if (!user?.id) return;
    try {
      const res = await apiClient.get(`/training/trainee/${user.id}`);
      const raw: any[] = res.data ?? [];
      // Backend returns newest-first; skip index 0 (today's record) — show history
      const history = raw.slice(1);
      // Each entry is a TrainingRecordResponse:
      //   id, record_date, current_day_number, trainer_id, trainee_id,
      //   trainer_rating, trainee_comments, submitted_at, is_locked, tasks (optional)
      const now = new Date();
      setRecords(history.map((r: any) => {
        const recordDate = r.record_date ? new Date(r.record_date) : null;
        // Review window: 2 days after the session
        const windowEnd = recordDate ? new Date(recordDate.getTime() + 2 * 86400000) : null;
        const windowOpen = windowEnd ? now <= windowEnd : false;
        const tasks: any[] = r.tasks ?? [];
        const taskDone  = tasks.filter((t: any) => t.is_completed).length;
        const taskTotal = tasks.length;
        return {
          record_id:            r.id,
          date:                 r.record_date ?? '',
          day_number:           r.current_day_number ?? 0,
          phase:                r.current_day_number ?? 0,
          trainer_name:         null, // not returned in list endpoint — omit
          task_completion_rate: taskTotal > 0 ? taskDone / taskTotal : 0,
          review_submitted:     !!r.trainee_comments || !!r.trainer_rating,
          review_window_open:   windowOpen,
          stars:                r.trainer_rating ?? null,
          comment:              r.trainee_comments ?? null,
        };
      }));
    } catch {
      setRecords([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [user?.id]);

  useEffect(() => { fetch(); }, [fetch]);

  const toggle = (id: string) =>
    setExpanded(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const setStars = (id: string, stars: number) =>
    setReviewState(prev => ({ ...prev, [id]: { ...prev[id] ?? { stars: 0, comment: '', submitting: false }, stars } }));

  const setComment = (id: string, comment: string) =>
    setReviewState(prev => ({ ...prev, [id]: { ...prev[id] ?? { stars: 0, comment: '', submitting: false }, comment } }));

  const submitReview = useCallback(async (record_id: string) => {
    const rv = reviewState[record_id];
    if (!rv || rv.stars === 0) { Alert.alert('Select a rating', 'Please choose 1–5 stars before submitting.'); return; }
    setReviewState(prev => ({ ...prev, [record_id]: { ...prev[record_id], submitting: true } }));
    try {
      await apiClient.post(`/training/record/${record_id}/review`, {
        trainer_rating:   rv.stars,
        trainee_comments: rv.comment,
      });
      Alert.alert('Submitted', 'Your review has been recorded.');
      fetch();
    } catch {
      Alert.alert('Error', 'Could not submit review. Try again.');
    } finally {
      setReviewState(prev => ({ ...prev, [record_id]: { ...prev[record_id], submitting: false } }));
    }
  }, [reviewState, fetch]);

  const s = styles(c);

  return (
    <ScreenShell
      edges={[]}
      noHeader
      title="Training History"
      subtitle="All past sessions"
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => { setRefreshing(true); fetch(); }}
    >
      {records.length === 0 ? (
        <View style={s.emptyCard}><Text style={s.emptyText}>No history yet</Text></View>
      ) : records.map(r => {
        const rv = reviewState[r.record_id] ?? { stars: r.stars ?? 0, comment: r.comment ?? '', submitting: false };
        const isExpanded = expanded.has(r.record_id);
        return (
          <TouchableOpacity key={r.record_id} style={s.card} onPress={() => toggle(r.record_id)} activeOpacity={0.8}>
            <View style={s.cardHeader}>
              <View style={{ flex: 1 }}>
                <Text style={s.dateText}>Day {r.day_number} · {r.date}</Text>
                <Text style={s.meta}>Phase {r.phase}{r.trainer_name ? ` · ${r.trainer_name}` : ''}</Text>
              </View>
              <View style={[s.rateBadge, { backgroundColor: rateColor(r.task_completion_rate, c) + '22' }]}>
                <Text style={[s.rateText, { color: rateColor(r.task_completion_rate, c) }]}>
                  {Math.round(r.task_completion_rate * 100)}%
                </Text>
              </View>
              <Text style={s.chevron}>{isExpanded ? '▲' : '▼'}</Text>
            </View>

            {isExpanded && (
              <View style={s.detail}>
                {/* Already reviewed */}
                {r.review_submitted && (
                  <View style={[s.noteBox, { backgroundColor: c.success + '12' }]}>
                    <Text style={[s.noteLabel, { color: c.success }]}>Your Review</Text>
                    <Text style={s.starRow}>{'★'.repeat(r.stars ?? 0)}{'☆'.repeat(5 - (r.stars ?? 0))}</Text>
                    {r.comment ? <Text style={s.noteText}>{r.comment}</Text> : null}
                  </View>
                )}

                {/* Review form — window open, not yet submitted */}
                {!r.review_submitted && r.review_window_open && (
                  <View style={s.reviewForm}>
                    <Text style={s.noteLabel}>Rate This Session</Text>
                    <Text style={s.hint}>Private — only management sees this</Text>
                    <View style={s.starPicker}>
                      {[1,2,3,4,5].map(star => (
                        <TouchableOpacity key={star} onPress={() => setStars(r.record_id, star)}>
                          <Text style={[s.starBtn, { color: star <= rv.stars ? c.gold : c.border }]}>★</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                    <TextInput
                      style={[s.textArea, { color: c.foreground, borderColor: c.border, backgroundColor: c.background }]}
                      value={rv.comment}
                      onChangeText={t => setComment(r.record_id, t)}
                      placeholder="Optional comment (private)…"
                      placeholderTextColor={c.mutedForeground}
                      multiline
                      numberOfLines={3}
                      textAlignVertical="top"
                    />
                    <TouchableOpacity
                      style={[s.btn, { backgroundColor: c.primary, opacity: rv.submitting ? 0.6 : 1 }]}
                      onPress={() => submitReview(r.record_id)}
                      disabled={rv.submitting}
                    >
                      {rv.submitting
                        ? <ActivityIndicator color="#fff" />
                        : <Text style={s.btnText}>Submit Review</Text>
                      }
                    </TouchableOpacity>
                  </View>
                )}

                {/* Window closed, not submitted */}
                {!r.review_submitted && !r.review_window_open && (
                  <Text style={[s.hint, { fontStyle: 'italic' }]}>Review window closed</Text>
                )}
              </View>
            )}
          </TouchableOpacity>
        );
      })}
    </ScreenShell>
  );
}

function rateColor(rate: number, c: ThemeColors) {
  if (rate >= 0.9) return c.success;
  if (rate >= 0.7) return c.warning;
  return c.danger;
}

const styles = (c: ThemeColors) => StyleSheet.create({
  card:       { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.sm },
  cardHeader: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  dateText:   { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground },
  meta:       { fontSize: fontSize.xs, color: c.mutedForeground, marginTop: 2 },
  rateBadge:  { paddingHorizontal: spacing.sm, paddingVertical: 3, borderRadius: radius.full },
  rateText:   { fontSize: fontSize.xs, fontWeight: fontWeight.bold },
  chevron:    { fontSize: fontSize.xs, color: c.mutedForeground },
  detail:     { marginTop: spacing.md, gap: spacing.sm },
  noteBox:    { borderRadius: radius.md, padding: spacing.sm },
  noteLabel:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 4 },
  noteText:   { fontSize: fontSize.sm, color: c.foreground, lineHeight: 20 },
  starRow:    { fontSize: fontSize.md, color: c.gold, marginBottom: 4 },
  reviewForm: { gap: spacing.sm },
  hint:       { fontSize: fontSize.xs, color: c.mutedForeground },
  starPicker: { flexDirection: 'row', gap: spacing.sm },
  starBtn:    { fontSize: 28 },
  textArea:   { borderWidth: 1, borderRadius: radius.md, padding: spacing.sm, fontSize: fontSize.sm, minHeight: 70 },
  btn:        { borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center' },
  btnText:    { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  emptyCard:  { backgroundColor: c.surfaceMuted, borderRadius: radius.lg, padding: spacing.xl, alignItems: 'center' },
  emptyText:  { fontSize: fontSize.base, color: c.mutedForeground },
});
