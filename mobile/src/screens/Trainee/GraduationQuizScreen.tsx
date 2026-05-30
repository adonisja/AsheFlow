import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, Alert, ScrollView,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// ── Types ─────────────────────────────────────────────────────────────────────

type QuizQuestion = {
  response_id: string;
  question_id: string;
  question_text: string;
  question_type: 'multiple_choice' | 'multi_select' | 'short_answer';
  choices: string[] | null;
  is_mandatory: boolean;
};

type QuizData = {
  quiz_id: string;
  attempt_number: number;
  questions: QuizQuestion[];
};

// answer_text for multi_select is pipe-delimited, e.g. "Choice A|Choice C"
type Answers = Record<string, string>; // question_id → answer_text

// ── Main component ────────────────────────────────────────────────────────────

export default function GraduationQuizScreen() {
  const c = useColors();
  const s = styles(c);

  const [loading,    setLoading]    = useState(true);
  const [quiz,       setQuiz]       = useState<QuizData | null>(null);
  const [answers,    setAnswers]    = useState<Answers>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitted,  setSubmitted]  = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiClient.get('/graduation-quiz/my-quiz');
      setQuiz(res.data);
      // Pre-fill blanks for all questions
      const initial: Answers = {};
      for (const q of res.data.questions) {
        initial[q.question_id] = '';
      }
      setAnswers(initial);
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setQuiz(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // ── Answer helpers ──

  function setSingleAnswer(questionId: string, value: string) {
    setAnswers(prev => ({ ...prev, [questionId]: value }));
  }

  function toggleMultiSelect(questionId: string, choice: string) {
    setAnswers(prev => {
      const current = prev[questionId] ? prev[questionId].split('|').filter(Boolean) : [];
      const updated = current.includes(choice)
        ? current.filter(c => c !== choice)
        : [...current, choice];
      return { ...prev, [questionId]: updated.join('|') };
    });
  }

  // ── Submit ──

  async function handleSubmit() {
    if (!quiz) return;

    // Validate mandatory questions
    const unanswered = quiz.questions.filter(
      q => q.is_mandatory && !answers[q.question_id]?.trim()
    );
    if (unanswered.length > 0) {
      Alert.alert(
        'Incomplete',
        `Please answer all required questions (${unanswered.length} remaining).`
      );
      return;
    }

    Alert.alert(
      'Submit Quiz',
      'Once submitted your answers cannot be changed. Are you sure?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Submit',
          onPress: async () => {
            setSubmitting(true);
            try {
              await apiClient.post('/graduation-quiz/submit', {
                quiz_id: quiz.quiz_id,
                responses: quiz.questions.map(q => ({
                  question_id: q.question_id,
                  answer_text: answers[q.question_id] ?? '',
                })),
              });
              setSubmitted(true);
            } catch (err: any) {
              const detail = err?.response?.data?.detail;
              Alert.alert('Error', detail ?? 'Could not submit quiz. Try again.');
            } finally {
              setSubmitting(false);
            }
          },
        },
      ]
    );
  }

  // ── Render ──

  if (loading) {
    return (
      <View style={s.center}>
        <ActivityIndicator size="large" color={c.primary} />
      </View>
    );
  }

  if (submitted) {
    return (
      <View style={s.center}>
        <Text style={{ fontSize: 48 }}>🎓</Text>
        <Text style={s.doneTitle}>Quiz submitted!</Text>
        <Text style={s.doneSub}>
          Your answers are under review. You will be notified once management has graded your quiz.
        </Text>
      </View>
    );
  }

  if (!quiz) {
    return (
      <ScreenShell edges={[]} noHeader title="Graduation Quiz" subtitle="">
        <View style={s.center}>
          <Text style={{ fontSize: 48 }}>📝</Text>
          <Text style={s.doneTitle}>No quiz available</Text>
          <Text style={s.doneSub}>
            Management will issue your graduation quiz when you're eligible. Check back soon.
          </Text>
        </View>
      </ScreenShell>
    );
  }

  const totalQ = quiz.questions.length;
  const answeredQ = quiz.questions.filter(q => !!answers[q.question_id]?.trim()).length;

  return (
    <ScrollView style={s.scroll} contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>

      {/* Header */}
      <View style={[s.headerCard, { backgroundColor: c.surface, borderColor: c.border }]}>
        <Text style={[s.headerTitle, { color: c.foreground }]}>Graduation Quiz</Text>
        <Text style={[s.headerSub, { color: c.mutedForeground }]}>
          Attempt {quiz.attempt_number} · {answeredQ}/{totalQ} answered
        </Text>
        <View style={[s.progressBar, { backgroundColor: c.border }]}>
          <View style={[s.progressFill, { backgroundColor: c.primary, width: `${totalQ > 0 ? (answeredQ / totalQ) * 100 : 0}%` as any }]} />
        </View>
      </View>

      {/* Questions */}
      {quiz.questions.map((q, idx) => (
        <QuestionBlock
          key={q.question_id}
          question={q}
          index={idx}
          answer={answers[q.question_id] ?? ''}
          onSingleChange={val => setSingleAnswer(q.question_id, val)}
          onMultiToggle={choice => toggleMultiSelect(q.question_id, choice)}
          c={c}
        />
      ))}

      {/* Submit */}
      <TouchableOpacity
        style={[s.submitBtn, { backgroundColor: c.primary, opacity: submitting ? 0.7 : 1 }]}
        onPress={handleSubmit}
        disabled={submitting}
        activeOpacity={0.8}
      >
        {submitting
          ? <ActivityIndicator size="small" color="#fff" />
          : <Text style={s.submitBtnText}>Submit Quiz</Text>
        }
      </TouchableOpacity>

      <View style={{ height: spacing.xl }} />
    </ScrollView>
  );
}

// ── Question block sub-component ──────────────────────────────────────────────

function QuestionBlock({
  question, index, answer, onSingleChange, onMultiToggle, c,
}: {
  question: QuizQuestion;
  index: number;
  answer: string;
  onSingleChange: (v: string) => void;
  onMultiToggle: (choice: string) => void;
  c: any;
}) {
  const s = styles(c);
  const selectedMulti = answer ? answer.split('|').filter(Boolean) : [];

  return (
    <View style={[s.questionCard, { backgroundColor: c.surface, borderColor: c.border }]}>
      <View style={s.questionHeader}>
        <Text style={[s.questionNum, { color: c.mutedForeground }]}>Q{index + 1}</Text>
        {question.is_mandatory && (
          <Text style={{ color: '#EF4444', fontSize: fontSize.xs, fontWeight: fontWeight.semibold }}>Required</Text>
        )}
      </View>
      <Text style={[s.questionText, { color: c.foreground }]}>{question.question_text}</Text>

      {question.question_type === 'short_answer' && (
        <TextInput
          style={[s.textInput, { borderColor: c.border, color: c.foreground, backgroundColor: c.background }]}
          multiline
          numberOfLines={3}
          placeholder="Your answer..."
          placeholderTextColor={c.mutedForeground}
          value={answer}
          onChangeText={onSingleChange}
        />
      )}

      {question.question_type === 'multiple_choice' && question.choices?.map(choice => {
        const selected = answer === choice;
        return (
          <TouchableOpacity
            key={choice}
            style={[s.choiceRow, {
              borderColor:     selected ? c.primary : c.border,
              backgroundColor: selected ? c.primary + '18' : c.surface,
            }]}
            onPress={() => onSingleChange(selected ? '' : choice)}
            activeOpacity={0.7}
          >
            <View style={[s.radio, { borderColor: selected ? c.primary : c.border, backgroundColor: selected ? c.primary : 'transparent' }]}>
              {selected && <View style={s.radioDot} />}
            </View>
            <Text style={[s.choiceText, { color: c.foreground }]}>{choice}</Text>
          </TouchableOpacity>
        );
      })}

      {question.question_type === 'multi_select' && question.choices?.map(choice => {
        const selected = selectedMulti.includes(choice);
        return (
          <TouchableOpacity
            key={choice}
            style={[s.choiceRow, {
              borderColor:     selected ? c.primary : c.border,
              backgroundColor: selected ? c.primary + '18' : c.surface,
            }]}
            onPress={() => onMultiToggle(choice)}
            activeOpacity={0.7}
          >
            <View style={[s.checkBox, { borderColor: selected ? c.primary : c.border, backgroundColor: selected ? c.primary : 'transparent' }]}>
              {selected && <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>✓</Text>}
            </View>
            <Text style={[s.choiceText, { color: c.foreground }]}>{choice}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  scroll:        { flex: 1, backgroundColor: c.background },
  center:        { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.sm, backgroundColor: c.background, padding: spacing.xl },
  doneTitle:     { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground, marginTop: spacing.sm },
  doneSub:       { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center' },

  headerCard:    { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: spacing.xs },
  headerTitle:   { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  headerSub:     { fontSize: fontSize.sm },
  progressBar:   { height: 6, borderRadius: 3, overflow: 'hidden', marginTop: spacing.xs },
  progressFill:  { height: 6, borderRadius: 3 },

  questionCard:  { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, gap: spacing.sm },
  questionHeader:{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  questionNum:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  questionText:  { fontSize: fontSize.base, fontWeight: fontWeight.medium, lineHeight: 22 },
  textInput:     { borderWidth: 1, borderRadius: radius.sm, padding: spacing.sm, fontSize: fontSize.sm, minHeight: 72, textAlignVertical: 'top' },

  choiceRow:     { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, padding: spacing.sm, borderWidth: 1, borderRadius: radius.sm },
  radio:         { width: 20, height: 20, borderRadius: 10, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  radioDot:      { width: 10, height: 10, borderRadius: 5, backgroundColor: '#fff' },
  checkBox:      { width: 20, height: 20, borderRadius: 4, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  choiceText:    { fontSize: fontSize.sm, flex: 1 },

  submitBtn:     { borderRadius: radius.md, padding: spacing.md, alignItems: 'center', marginTop: spacing.sm },
  submitBtnText: { color: '#fff', fontSize: fontSize.base, fontWeight: fontWeight.bold },
});
