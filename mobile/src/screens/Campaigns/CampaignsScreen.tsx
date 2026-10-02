/**
 * Campaigns — the field surface on mobile (ADR-485 D6/D10).
 *
 * Replaces DriverSurveyScreen, whose four questions were four pieces of
 * hardcoded state. Questions now come from the server, so an admin adding one
 * needs no app release — which was the point of the whole ADR and is wasted if
 * the mobile client still knows the question list.
 *
 * THE TWO DESIGN RULES FROM D6, both load-bearing here:
 *
 *  1. **Lead with the date and the truck.** A daily campaign routinely has two
 *     runs open at once (D12) — yesterday's, closing at this morning's shift
 *     start, and today's. Two cards reading "Driver Survey" with no date is
 *     the one confusion this design can still produce.
 *  2. **Bool is two buttons, not a picker.** One tap, visible state, on a
 *     phone in a van. Carried over from the screen this replaces.
 */
import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator, RefreshControl, ScrollView, StyleSheet, Text,
  TextInput, TouchableOpacity, View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ---------------------------------------------------------------------------
// Shapes — mirror of the API (ADR-485 D5). Hand-maintained: no codegen.
// ---------------------------------------------------------------------------

interface Question {
  id: string;
  position: number;
  prompt: string;
  kind: 'bool' | 'scale' | 'text' | 'choice';
  required: boolean;
  scale_min?: number | null;
  scale_max?: number | null;
  choices?: string[] | null;
}

interface OpenRun {
  run_id: string;
  campaign_label: string;
  date: string;
  closes_at: string;
  subject_id: string;
  subject_name: string;
  truck_name?: string | null;
  answered: boolean;
  questions: Question[];
  /** First names of the crew on this assignment, for the D14 name warning. */
  crew_names?: string[];
}

type Answer = { bool?: boolean; int?: number; text?: string };
type Draft = Record<string, Answer>;

function closesIn(iso: string): { label: string; urgent: boolean } {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return { label: 'Closed', urgent: true };
  const hours = Math.floor(ms / 3_600_000);
  const mins = Math.floor((ms % 3_600_000) / 60_000);
  // Under two hours is where a reminder stops being information and starts
  // being a deadline — ADR-130's threshold, kept.
  if (hours < 2) return { label: `Closes in ${hours}h ${mins}m`, urgent: true };
  return { label: `Closes in ${hours}h`, urgent: false };
}

/**
 * Does this free text name someone on the crew? (ADR-485 D14)
 *
 * Word boundaries, case-insensitive. Without \b, an employee named Al makes
 * "the van was almost empty" a false positive — and a warning that fires on
 * ordinary sentences is one people learn to dismiss.
 */
function namesACoworker(text: string, crew?: string[]): boolean {
  if (!text || !crew?.length) return false;
  return crew.some(name => {
    if (name.length < 3) return false;   // "Al" matches inside too much
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`\\b${escaped}\\b`, 'i').test(text);
  });
}

// ---------------------------------------------------------------------------

function YesNo({ value, onChange }: {
  value: boolean | undefined;
  onChange: (v: boolean) => void;
}) {
  const c = useColors();
  const s = toggleStyles(c);
  return (
    <View style={s.buttons}>
      <TouchableOpacity
        style={[s.btn, value === true && s.btnYes]}
        onPress={() => onChange(true)}
        activeOpacity={0.7}
        accessibilityRole="button"
        accessibilityLabel="Yes"
      >
        <Text style={[s.btnText, value === true && s.btnYesText]}>Yes</Text>
      </TouchableOpacity>
      <TouchableOpacity
        style={[s.btn, value === false && s.btnNo]}
        onPress={() => onChange(false)}
        activeOpacity={0.7}
        accessibilityRole="button"
        accessibilityLabel="No"
      >
        <Text style={[s.btnText, value === false && s.btnNoText]}>No</Text>
      </TouchableOpacity>
    </View>
  );
}

export default function CampaignsScreen() {
  const c = useColors();
  const s = styles(c);

  const [runs, setRuns] = useState<OpenRun[] | null>(null);
  const [active, setActive] = useState<OpenRun | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get<OpenRun[]>('/campaigns/my-open');
      setRuns(res.data);
      setError(null);
    } catch (err) {
      setError(errorText(err, 'Could not load your campaigns.'));
      setRuns([]);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }, [load]);

  const setAnswer = (qid: string, value: Answer) =>
    setDraft(d => ({ ...d, [qid]: value }));

  const submit = async () => {
    if (!active) return;
    setSubmitting(true);
    setError(null);
    try {
      await apiClient.post(`/campaigns/runs/${active.run_id}/respond`, {
        subject_id: active.subject_id,
        answers: active.questions
          .filter(q => draft[q.id] !== undefined)
          .map(q => ({
            question_id: q.id,
            bool_value: q.kind === 'bool' ? draft[q.id].bool : null,
            int_value: q.kind === 'scale' || q.kind === 'choice'
              ? draft[q.id].int : null,
            text_value: q.kind === 'text' ? draft[q.id].text : null,
          })),
      });
      setDone(`Thanks. Your answers about ${active.subject_name} are in.`);
      setActive(null);
      setDraft({});
      await load();
    } catch (err) {
      /* The server validates each answer against its own question and names
         the one that is wrong. Surfacing that beats a generic failure on a
         form somebody just filled in. */
      setError(errorText(err, 'Could not submit your answers.'));
    } finally {
      setSubmitting(false);
    }
  };

  // ---- the form ----------------------------------------------------------

  if (active) {
    const closing = closesIn(active.closes_at);
    return (
      <SafeAreaView style={s.safe} edges={['top']}>
        <ScrollView contentContainerStyle={s.content}>
          <TouchableOpacity onPress={() => { setActive(null); setError(null); }}>
            <Text style={s.back}>‹ Back</Text>
          </TouchableOpacity>

          <View style={s.card}>
            <Text style={s.title}>{active.campaign_label}</Text>
            <Text style={s.meta}>
              {active.date}
              {active.truck_name ? ` · ${active.truck_name}` : ''}
            </Text>
            <Text style={s.subject}>About {active.subject_name}</Text>
            <Text style={[s.closing, closing.urgent && s.closingUrgent]}>
              {closing.label}
            </Text>
          </View>

          {error && <Text style={s.error}>{error}</Text>}

          <View style={s.card}>
            {active.questions.map(q => (
              <View key={q.id} style={s.question}>
                <Text style={s.prompt}>
                  {q.prompt}
                  {!q.required && <Text style={s.optional}> (optional)</Text>}
                </Text>

                {q.kind === 'bool' && (
                  <YesNo
                    value={draft[q.id]?.bool}
                    onChange={v => setAnswer(q.id, { bool: v })}
                  />
                )}

                {q.kind === 'scale' && (
                  <View style={s.scaleRow}>
                    {Array.from(
                      { length: (q.scale_max ?? 5) - (q.scale_min ?? 1) + 1 },
                      (_, i) => (q.scale_min ?? 1) + i,
                    ).map(n => (
                      <TouchableOpacity
                        key={n}
                        style={[s.scaleBtn, draft[q.id]?.int === n && s.scaleOn]}
                        onPress={() => setAnswer(q.id, { int: n })}
                        activeOpacity={0.7}
                      >
                        <Text style={[s.scaleText,
                                      draft[q.id]?.int === n && s.scaleTextOn]}>
                          {n}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                )}

                {q.kind === 'choice' && (
                  /* The option INDEX is the value — renaming an option later
                     must not rewrite what a past answer meant (D2). */
                  <View style={s.choices}>
                    {(q.choices ?? []).map((label, i) => (
                      <TouchableOpacity
                        key={label}
                        style={[s.choice, draft[q.id]?.int === i && s.choiceOn]}
                        onPress={() => setAnswer(q.id, { int: i })}
                        activeOpacity={0.7}
                      >
                        <Text style={[s.choiceText,
                                      draft[q.id]?.int === i && s.choiceTextOn]}>
                          {label}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                )}

                {q.kind === 'text' && (
                  <>
                    <TextInput
                      style={s.input}
                      value={draft[q.id]?.text ?? ''}
                      onChangeText={t => setAnswer(q.id, { text: t })}
                      maxLength={2000}
                      multiline
                      numberOfLines={3}
                      placeholder="Optional"
                      placeholderTextColor={c.placeholder}
                      accessibilityLabel={q.prompt}
                    />
                    {/* A WARNING, not a block (D14). A hard refusal on 2000
                        characters somebody just typed is how a report gets
                        abandoned instead of rewritten. */}
                    {namesACoworker(draft[q.id]?.text ?? '', active.crew_names) && (
                      <Text style={s.warn}>
                        This mentions a coworker by name. Reviews are about{' '}
                        {active.subject_name}, so use someone's role if you need
                        to refer to them.
                      </Text>
                    )}
                  </>
                )}
              </View>
            ))}
          </View>

          <TouchableOpacity
            style={[s.submit, submitting && s.submitDisabled]}
            onPress={() => void submit()}
            disabled={submitting}
            activeOpacity={0.8}
          >
            {submitting
              ? <ActivityIndicator color={c.primaryForeground} />
              : <Text style={s.submitText}>Submit</Text>}
          </TouchableOpacity>

          <Text style={s.footnote}>
            Your answers go to management, never to {active.subject_name}.
          </Text>
        </ScrollView>
      </SafeAreaView>
    );
  }

  // ---- the list ----------------------------------------------------------

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      <ScrollView
        contentContainerStyle={s.content}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh}
                          tintColor={c.primary} />
        }
      >
        <Text style={s.heading}>Campaigns</Text>

        {done && <Text style={s.success}>{done}</Text>}
        {error && <Text style={s.error}>{error}</Text>}

        {runs === null && (
          <ActivityIndicator style={s.loading} color={c.primary} />
        )}

        {runs !== null && runs.length === 0 && (
          <View style={s.card}>
            <Text style={s.emptyTitle}>Nothing to answer right now.</Text>
            <Text style={s.emptyBody}>
              You will see a campaign here while one is open for a shift you
              worked.
            </Text>
          </View>
        )}

        {runs?.map(run => {
          const closing = closesIn(run.closes_at);
          return (
            <TouchableOpacity
              key={`${run.run_id}-${run.subject_id}`}
              style={[s.card, run.answered && s.cardDone]}
              onPress={() => { setActive(run); setDraft({}); setDone(null); }}
              disabled={run.answered}
              activeOpacity={0.7}
            >
              <Text style={s.title}>{run.campaign_label}</Text>
              {/* Date and truck, always — two open runs of the same campaign
                  are told apart by nothing else. */}
              <Text style={s.meta}>
                {run.date}
                {run.truck_name ? ` · ${run.truck_name}` : ''}
                {' · '}About {run.subject_name}
              </Text>
              <Text style={[
                s.closing,
                run.answered ? s.closingDone : closing.urgent && s.closingUrgent,
              ]}>
                {run.answered ? 'Done' : closing.label}
              </Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}

const toggleStyles = (c: ThemeColors) => StyleSheet.create({
  buttons:    { flexDirection: 'row', gap: spacing.sm },
  btn:        { flex: 1, paddingVertical: spacing.xs + 4, borderRadius: radius.md,
                borderWidth: 1.5, borderColor: c.border, alignItems: 'center' },
  btnYes:     { backgroundColor: c.success + '20', borderColor: c.success },
  btnNo:      { backgroundColor: c.danger + '20', borderColor: c.danger },
  btnText:    { fontSize: fontSize.sm, color: c.mutedForeground,
                fontWeight: fontWeight.medium },
  btnYesText: { color: c.success },
  btnNoText:  { color: c.danger },
});

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:        { flex: 1, backgroundColor: c.background },
  content:     { padding: spacing.md, gap: spacing.md, paddingBottom: spacing.xl },
  heading:     { fontSize: fontSize.xl, fontWeight: fontWeight.semibold,
                 color: c.foreground },
  back:        { fontSize: fontSize.md, color: c.primary },
  card:        { backgroundColor: c.card, borderRadius: radius.lg,
                 padding: spacing.md, borderWidth: 1, borderColor: c.border,
                 gap: spacing.xs },
  cardDone:    { opacity: 0.6 },
  title:       { fontSize: fontSize.md, fontWeight: fontWeight.semibold,
                 color: c.foreground },
  meta:        { fontSize: fontSize.xs, color: c.mutedForeground },
  subject:     { fontSize: fontSize.sm, color: c.foreground,
                 fontWeight: fontWeight.medium },
  closing:     { fontSize: fontSize.xs, color: c.mutedForeground },
  closingUrgent: { color: c.warning },
  closingDone: { color: c.success },
  question:    { marginBottom: spacing.md, gap: spacing.xs },
  prompt:      { fontSize: fontSize.sm, color: c.foreground,
                 fontWeight: fontWeight.medium, lineHeight: 20 },
  optional:    { color: c.mutedForeground, fontWeight: fontWeight.regular },
  scaleRow:    { flexDirection: 'row', gap: spacing.sm, flexWrap: 'wrap' },
  scaleBtn:    { width: 44, height: 44, borderRadius: radius.md, borderWidth: 1.5,
                 borderColor: c.border, alignItems: 'center',
                 justifyContent: 'center' },
  scaleOn:     { backgroundColor: c.primary + '20', borderColor: c.primary },
  scaleText:   { fontSize: fontSize.sm, color: c.mutedForeground },
  scaleTextOn: { color: c.primary, fontWeight: fontWeight.semibold },
  choices:     { gap: spacing.sm },
  choice:      { paddingVertical: spacing.xs + 4, paddingHorizontal: spacing.md,
                 borderRadius: radius.md, borderWidth: 1.5, borderColor: c.border },
  choiceOn:    { backgroundColor: c.primary + '20', borderColor: c.primary },
  choiceText:  { fontSize: fontSize.sm, color: c.foreground },
  choiceTextOn:{ color: c.primary, fontWeight: fontWeight.medium },
  input:       { borderWidth: 1, borderColor: c.border, borderRadius: radius.md,
                 padding: spacing.sm, fontSize: fontSize.sm, color: c.foreground,
                 minHeight: 80, textAlignVertical: 'top' },
  warn:        { fontSize: fontSize.xs, color: c.warning, lineHeight: 18 },
  submit:      { backgroundColor: c.primary, borderRadius: radius.lg,
                 paddingVertical: spacing.sm + 4, alignItems: 'center' },
  submitDisabled: { opacity: 0.6 },
  submitText:  { color: c.primaryForeground, fontSize: fontSize.md,
                 fontWeight: fontWeight.semibold },
  footnote:    { fontSize: fontSize.xs, color: c.mutedForeground,
                 textAlign: 'center' },
  error:       { fontSize: fontSize.sm, color: c.danger, padding: spacing.sm,
                 backgroundColor: c.danger + '10', borderRadius: radius.md },
  success:     { fontSize: fontSize.sm, color: c.success, padding: spacing.sm,
                 backgroundColor: c.success + '10', borderRadius: radius.md },
  loading:     { marginTop: spacing.xl },
  emptyTitle:  { fontSize: fontSize.sm, color: c.foreground },
  emptyBody:   { fontSize: fontSize.xs, color: c.mutedForeground },
});
