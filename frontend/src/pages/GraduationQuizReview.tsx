import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { CheckCircle2, XCircle, ChevronDown, ChevronUp, ArrowLeft } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import MotionCard from '../components/ui/MotionCard';
import { SkeletonCard } from '../components/ui/Skeleton';
import ErrorBanner from '../components/ui/ErrorBanner';

interface QuizResponse {
  id: string;
  question_id: string;
  question_text: string;
  question_type: string;
  choices: string[] | null;
  correct_answer: string | null;
  is_mandatory: boolean;
  answer_text: string | null;
  auto_correct: boolean | null;
  manager_override: boolean | null;
  override_note: string | null;
}

interface QuizDetail {
  id: string;
  trainee_id: string;
  trainee_name: string | null;
  attempt_number: number;
  status: string;
  auto_score: number | null;
  final_score: number | null;
  passed: boolean | null;
  weak_topics: string[];
  submitted_at: string | null;
  manager_reviewed_at: string | null;
  responses: QuizResponse[];
}

interface Override {
  response_id: string;
  correct: boolean;
  note: string;
}

export default function GraduationQuizReview() {
  const { quizId } = useParams<{ quizId: string }>();
  const navigate = useNavigate();

  const [quiz, setQuiz] = useState<QuizDetail | null>(null);
  const [overrides, setOverrides] = useState<Record<string, Override>>({});
  const [finalPass, setFinalPass] = useState<boolean | null>(null);
  const [sendForTraining, setSendForTraining] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedNotes, setExpandedNotes] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!quizId) return;
    axiosClient.get(`/graduation-quiz/${quizId}`)
      .then(r => {
        setQuiz(r.data);
        // Pre-set finalPass based on auto-score as a starting point
        if (r.data.auto_score !== null) {
          setFinalPass(r.data.auto_score >= 90);
        }
      })
      .catch(() => setError('Failed to load quiz.'))
      .finally(() => setLoading(false));
  }, [quizId]);

  function effectiveCorrect(response: QuizResponse): boolean | null {
    const override = overrides[response.id];
    if (override) return override.correct;
    if (response.manager_override !== null) return response.manager_override;
    return response.auto_correct;
  }

  function setOverrideCorrect(responseId: string, correct: boolean) {
    setOverrides(prev => ({
      ...prev,
      [responseId]: { ...prev[responseId], response_id: responseId, correct, note: prev[responseId]?.note || '' },
    }));
  }

  function setOverrideNote(responseId: string, note: string) {
    setOverrides(prev => ({
      ...prev,
      [responseId]: { ...prev[responseId], response_id: responseId, note, correct: prev[responseId]?.correct ?? (quiz?.responses.find(r => r.id === responseId)?.auto_correct ?? false) },
    }));
  }

  // Compute live score from current overrides
  function computeCurrentScore(): { score: number; allPass: boolean } {
    if (!quiz) return { score: 0, allPass: false };
    const mandatory = quiz.responses.filter(r => r.is_mandatory);
    if (mandatory.length === 0) return { score: 100, allPass: true };
    const passed = mandatory.filter(r => effectiveCorrect(r) === true).length;
    const score = (passed / mandatory.length) * 100;
    const allPass = mandatory.every(r => effectiveCorrect(r) === true);
    return { score, allPass };
  }

  async function handleConfirm() {
    if (!quiz || finalPass === null) return;
    setSubmitting(true);
    setError(null);
    try {
      await axiosClient.patch(`/graduation-quiz/${quiz.id}/review`, {
        overrides: Object.values(overrides),
        final_pass: finalPass,
        send_for_training: sendForTraining,
      });
      setDone(true);
    } catch {
      setError('Failed to submit review. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="p-6 space-y-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>;
  if (error && !quiz) return <div className="p-6"><ErrorBanner message={error} /></div>;
  if (!quiz) return null;

  if (done) {
    return (
      <div className="p-6 max-w-2xl mx-auto">
        <MotionCard hoverable={false}>
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <CheckCircle2 className="w-14 h-14 text-success" />
            <p className="text-xl font-bold text-foreground">Review Confirmed</p>
            <p className="text-sm text-muted-foreground">
              {finalPass
                ? `${quiz.trainee_name ?? 'Trainee'} will be promoted to Walker on their next dispatch day.`
                : `${quiz.trainee_name ?? 'Trainee'} has been referred for additional training.`}
            </p>
            <button
              onClick={() => navigate(-1)}
              className="mt-2 flex items-center gap-1.5 text-sm text-primary hover:underline"
            >
              <ArrowLeft className="w-4 h-4" /> Back
            </button>
          </div>
        </MotionCard>
      </div>
    );
  }

  const { score: liveScore, allPass: liveAllPass } = computeCurrentScore();
  const likelyPass = liveScore >= 90 && liveAllPass;

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="w-4 h-4" /> Back
      </button>

      <SectionHeader
        title={`Quiz Review — ${quiz.trainee_name ?? 'Trainee'}`}
        description={`Attempt ${quiz.attempt_number} · Submitted ${quiz.submitted_at ? new Date(quiz.submitted_at).toLocaleDateString() : '—'}`}
      />

      {error && <ErrorBanner message={error} />}

      {/* Score summary */}
      <MotionCard hoverable={false}>
        <div className="flex flex-wrap gap-6 items-center">
          <div className="text-center">
            <p className="text-3xl font-bold text-foreground">{liveScore.toFixed(1)}%</p>
            <p className="text-xs text-muted-foreground mt-0.5">Current score</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-semibold text-foreground">{quiz.auto_score?.toFixed(1) ?? '—'}%</p>
            <p className="text-xs text-muted-foreground mt-0.5">Auto score</p>
          </div>
          <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium ${
            likelyPass ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'
          }`}>
            {likelyPass ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
            {likelyPass ? 'Likely Pass' : 'Likely Fail'}
          </div>
        </div>
        {quiz.weak_topics.length > 0 && (
          <div className="mt-4 border-t border-border pt-4">
            <p className="text-xs font-semibold text-muted-foreground mb-2">Weak topics (auto-identified):</p>
            <div className="flex flex-wrap gap-1.5">
              {quiz.weak_topics.map(topic => (
                <span key={topic} className="text-xs bg-danger/10 text-danger px-2 py-0.5 rounded-full">
                  {topic.length > 60 ? topic.slice(0, 57) + '…' : topic}
                </span>
              ))}
            </div>
          </div>
        )}
      </MotionCard>

      {/* Per-question review */}
      {quiz.responses.map((response, idx) => {
        const effective = effectiveCorrect(response);
        const hasOverride = !!overrides[response.id];
        const noteExpanded = expandedNotes[response.id] ?? false;

        return (
          <MotionCard key={response.id} delay={idx * 0.03} hoverable={false}>
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex gap-2 flex-1">
                  <span className="text-xs font-bold text-muted-foreground mt-0.5 shrink-0">{idx + 1}.</span>
                  <div className="space-y-1 flex-1">
                    <p className="text-sm font-medium text-foreground leading-snug">
                      {response.question_text}
                      {response.is_mandatory && <span className="text-danger ml-1">*</span>}
                    </p>
                    {response.question_type === 'short_answer' && (
                      <span className="text-xs text-muted-foreground italic">Short answer</span>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {effective === true && <CheckCircle2 className="w-5 h-5 text-success" />}
                  {effective === false && <XCircle className="w-5 h-5 text-danger" />}
                  {effective === null && <span className="text-xs text-muted-foreground">—</span>}
                  {hasOverride && (
                    <span className="text-xs bg-warning/10 text-warning px-1.5 py-0.5 rounded ml-1">overridden</span>
                  )}
                </div>
              </div>

              {/* Trainee's answer */}
              <div className="pl-5 space-y-1">
                <p className="text-xs font-semibold text-muted-foreground">Trainee's answer:</p>
                <p className="text-sm text-foreground bg-accent rounded-lg px-3 py-2">
                  {response.answer_text
                    ? response.answer_text.replace(/\|/g, ', ')
                    : <span className="italic text-muted-foreground">No answer</span>}
                </p>
              </div>

              {/* Correct answer (for MC) */}
              {response.question_type === 'multiple_choice' && response.correct_answer && (
                <div className="pl-5 space-y-1">
                  <p className="text-xs font-semibold text-muted-foreground">Correct answer:</p>
                  <p className="text-sm text-success bg-success/5 rounded-lg px-3 py-2">
                    {response.correct_answer.replace(/\|/g, ', ')}
                  </p>
                </div>
              )}

              {/* Override controls */}
              <div className="pl-5 flex flex-wrap gap-2 pt-1">
                <button
                  onClick={() => setOverrideCorrect(response.id, true)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                    overrides[response.id]?.correct === true
                      ? 'bg-success/10 border-success text-success font-medium'
                      : 'border-border text-muted-foreground hover:border-success hover:text-success'
                  }`}
                >
                  Mark correct
                </button>
                <button
                  onClick={() => setOverrideCorrect(response.id, false)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                    overrides[response.id]?.correct === false
                      ? 'bg-danger/10 border-danger text-danger font-medium'
                      : 'border-border text-muted-foreground hover:border-danger hover:text-danger'
                  }`}
                >
                  Mark incorrect
                </button>
                <button
                  onClick={() => setExpandedNotes(prev => ({ ...prev, [response.id]: !prev[response.id] }))}
                  className="text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
                >
                  Note {noteExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
              </div>

              {noteExpanded && (
                <div className="pl-5">
                  <textarea
                    rows={2}
                    placeholder="Optional note for this question…"
                    value={overrides[response.id]?.note ?? response.override_note ?? ''}
                    onChange={e => setOverrideNote(response.id, e.target.value)}
                    className="w-full text-sm border border-border rounded-lg px-3 py-2 bg-background text-foreground resize-none focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                </div>
              )}
            </div>
          </MotionCard>
        );
      })}

      {/* Final verdict */}
      <MotionCard delay={quiz.responses.length * 0.03} hoverable={false}>
        <div className="space-y-4">
          <p className="text-sm font-semibold text-foreground">Final verdict</p>
          <div className="flex gap-3">
            <button
              onClick={() => { setFinalPass(true); setSendForTraining(false); }}
              className={`flex-1 py-3 rounded-xl border text-sm font-medium transition-colors ${
                finalPass === true
                  ? 'bg-success/10 border-success text-success'
                  : 'border-border text-muted-foreground hover:border-success hover:text-success'
              }`}
            >
              Pass — Promote to Walker
            </button>
            <button
              onClick={() => { setFinalPass(false); }}
              className={`flex-1 py-3 rounded-xl border text-sm font-medium transition-colors ${
                finalPass === false
                  ? 'bg-danger/10 border-danger text-danger'
                  : 'border-border text-muted-foreground hover:border-danger hover:text-danger'
              }`}
            >
              Fail
            </button>
          </div>

          {finalPass === false && (
            <div className="flex items-center gap-3 pt-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={sendForTraining}
                  onChange={e => setSendForTraining(e.target.checked)}
                  className="w-4 h-4 rounded accent-primary"
                />
                <span className="text-sm text-foreground">
                  Schedule additional training on weak topics
                </span>
              </label>
            </div>
          )}

          {finalPass === false && !sendForTraining && (
            <p className="text-xs text-muted-foreground">
              Without scheduling training, the trainee will remain in trainee status
              until further action is taken.
            </p>
          )}

          <button
            onClick={handleConfirm}
            disabled={submitting || finalPass === null}
            className="w-full py-3 rounded-xl bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Saving…' : 'Confirm & Save'}
          </button>
        </div>
      </MotionCard>
    </div>
  );
}
