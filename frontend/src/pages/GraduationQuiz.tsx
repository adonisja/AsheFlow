import React, { useEffect, useState } from 'react';
import { CheckCircle2, Send, ClipboardList } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import MotionCard from '../components/ui/MotionCard';
import { SkeletonCard } from '../components/ui/Skeleton';
import ErrorBanner from '../components/ui/ErrorBanner';

interface QuizQuestion {
  response_id: string;
  question_id: string;
  question_text: string;
  question_type: 'multiple_choice' | 'short_answer';
  choices: string[] | null;
  is_mandatory: boolean;
}

interface ActiveQuiz {
  quiz_id: string;
  attempt_number: number;
  questions: QuizQuestion[];
}

export default function GraduationQuiz() {
  const [quiz, setQuiz] = useState<ActiveQuiz | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});        // response_id → answer_text
  const [multiSelect, setMultiSelect] = useState<Record<string, string[]>>({}); // response_id → selected[]
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axiosClient.get('/graduation-quiz/my-quiz')
      .then(r => {
        setQuiz(r.data);
        // Initialise empty answers
        const emptyAnswers: Record<string, string> = {};
        const emptyMulti: Record<string, string[]> = {};
        for (const q of r.data.questions) {
          emptyAnswers[q.response_id] = '';
          if (q.question_type === 'multiple_choice' && q.choices) {
            emptyMulti[q.response_id] = [];
          }
        }
        setAnswers(emptyAnswers);
        setMultiSelect(emptyMulti);
      })
      .catch(err => {
        if (err.response?.status === 404) {
          setQuiz(null); // no active quiz
        } else {
          setError('Failed to load quiz.');
        }
      })
      .finally(() => setLoading(false));
  }, []);

  function handleTextChange(responseId: string, value: string) {
    setAnswers(prev => ({ ...prev, [responseId]: value }));
  }

  function handleSingleSelect(responseId: string, choice: string) {
    setAnswers(prev => ({ ...prev, [responseId]: choice }));
  }

  function handleMultiToggle(responseId: string, choice: string) {
    setMultiSelect(prev => {
      const current = prev[responseId] || [];
      const updated = current.includes(choice)
        ? current.filter(c => c !== choice)
        : [...current, choice];
      return { ...prev, [responseId]: updated };
    });
  }

  // Determine if a MC question is multi-select (correct_answer contains '|')
  // We don't have correct_answer here (hidden from trainee) so we infer from
  // choices count and question_text containing "4" or "2" as a hint.
  // Instead, simply allow multi-select on all MC questions — the submit path
  // joins selected values with '|' so the scorer handles both cases.

  function buildResponses() {
    if (!quiz) return [];
    return quiz.questions.map(q => {
      let answer_text: string;
      if (q.question_type === 'multiple_choice') {
        const selected = multiSelect[q.response_id] || [];
        answer_text = selected.length > 0 ? selected.join('|') : (answers[q.response_id] || '');
      } else {
        answer_text = answers[q.response_id] || '';
      }
      return { question_id: q.question_id, answer_text };
    });
  }

  function isComplete() {
    if (!quiz) return false;
    return quiz.questions.every(q => {
      if (q.question_type === 'multiple_choice') {
        return (multiSelect[q.response_id] || []).length > 0;
      }
      return (answers[q.response_id] || '').trim().length > 0;
    });
  }

  async function handleSubmit() {
    if (!quiz || !isComplete()) return;
    setSubmitting(true);
    setError(null);
    try {
      await axiosClient.post('/graduation-quiz/submit', {
        quiz_id: quiz.quiz_id,
        responses: buildResponses(),
      });
      setSubmitted(true);
    } catch {
      setError('Failed to submit quiz. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="p-6 space-y-4"><SkeletonCard /><SkeletonCard /></div>;

  if (submitted) {
    return (
      <div className="p-6 max-w-2xl mx-auto">
        <MotionCard hoverable={false}>
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <CheckCircle2 className="w-14 h-14 text-success" />
            <p className="text-xl font-bold text-foreground">Quiz Submitted</p>
            <p className="text-sm text-muted-foreground max-w-sm">
              Your answers have been recorded. A manager will review your results
              and notify you of the outcome shortly.
            </p>
          </div>
        </MotionCard>
      </div>
    );
  }

  if (!quiz) {
    return (
      <div className="p-6 max-w-2xl mx-auto">
        <MotionCard hoverable={false}>
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <ClipboardList className="w-14 h-14 text-muted-foreground" />
            <p className="text-lg font-semibold text-foreground">No Active Quiz</p>
            <p className="text-sm text-muted-foreground">
              Your quiz will appear here once it has been issued by your manager.
            </p>
          </div>
        </MotionCard>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <SectionHeader
        title="Graduation Quiz"
        description={`Attempt ${quiz.attempt_number} · ${quiz.questions.length} questions · Answer all questions before submitting`}
      />

      {error && <ErrorBanner message={error} />}

      {quiz.questions.map((q, idx) => (
        <MotionCard key={q.response_id} delay={idx * 0.04} hoverable={false}>
          <div className="space-y-3">
            <div className="flex gap-2">
              <span className="text-xs font-bold text-muted-foreground mt-0.5 shrink-0">
                {idx + 1}.
              </span>
              <p className="text-sm font-medium text-foreground leading-snug">
                {q.question_text}
                {q.is_mandatory && <span className="text-danger ml-1">*</span>}
              </p>
            </div>

            {q.question_type === 'multiple_choice' && q.choices ? (
              <div className="space-y-2 pl-5">
                {q.choices.map(choice => {
                  const selected = (multiSelect[q.response_id] || []).includes(choice);
                  return (
                    <button
                      key={choice}
                      onClick={() => handleMultiToggle(q.response_id, choice)}
                      className={`w-full text-left text-sm px-3 py-2 rounded-lg border transition-colors ${
                        selected
                          ? 'border-primary bg-primary/10 text-primary font-medium'
                          : 'border-border bg-background text-foreground hover:bg-accent'
                      }`}
                    >
                      {choice}
                    </button>
                  );
                })}
              </div>
            ) : (
              <textarea
                rows={3}
                placeholder="Your answer..."
                value={answers[q.response_id] || ''}
                onChange={e => handleTextChange(q.response_id, e.target.value)}
                className="w-full pl-5 text-sm border border-border rounded-lg px-3 py-2 bg-background text-foreground resize-none focus:outline-none focus:ring-2 focus:ring-primary/50"
              />
            )}
          </div>
        </MotionCard>
      ))}

      <MotionCard delay={quiz.questions.length * 0.04} hoverable={false}>
        <div className="flex items-center justify-between gap-4">
          <p className="text-xs text-muted-foreground">
            {quiz.questions.filter(q => {
              if (q.question_type === 'multiple_choice') {
                return (multiSelect[q.response_id] || []).length > 0;
              }
              return (answers[q.response_id] || '').trim().length > 0;
            }).length} / {quiz.questions.length} answered
          </p>
          <button
            onClick={handleSubmit}
            disabled={submitting || !isComplete()}
            className="flex items-center gap-2 px-5 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="w-4 h-4" />
            {submitting ? 'Submitting…' : 'Submit Quiz'}
          </button>
        </div>
      </MotionCard>
    </div>
  );
}
