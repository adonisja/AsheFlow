import React, { useEffect, useState } from 'react';
import { CheckCircle2, Circle, Send, ClipboardList, AlertTriangle } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import MotionCard from '../components/ui/MotionCard';
import { SkeletonCard } from '../components/ui/Skeleton';

interface Task {
  id: string;
  topic_title: string;
  description: string | null;
  is_mandatory: boolean;
  is_completed: boolean;
  record_type: string;
}

interface Record {
  id: string;
  current_day_number: number;
  trainee_id: string;
  submitted_at: string | null;
  phase_closed: boolean;
  observation_notes: string | null;
}

interface ScorePreview {
  score_preview: number;
  would_pass: boolean;
  failed_mandatory_topics: string[];
  total_mandatory: number;
  passed_mandatory: number;
}

export default function Phase4Observation() {
  const [record, setRecord] = useState<Record | null>(null);
  const [trainee, setTrainee] = useState<{ id: string; name: string } | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [notes, setNotes] = useState('');
  const [scorePreview, setScorePreview] = useState<ScorePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [submitResult, setSubmitResult] = useState<{ score: number; passed: boolean; failed: string[] } | null>(null);

  useEffect(() => {
    axiosClient.get('/training/trainer/today')
      .then(r => {
        const data = r.data;
        if (!data.record || data.record.current_day_number !== 4) {
          setLoading(false);
          return;
        }
        setRecord(data.record);
        setTrainee(data.trainee);
        setNotes(data.record.observation_notes ?? '');

        // Fetch tasks for this record
        return axiosClient.get(`/training/trainee/${data.record.trainee_id}`)
          .then(hist => {
            const rec = (hist.data as any[]).find((r: any) => r.id === data.record.id);
            if (rec?.tasks) {
              setTasks(rec.tasks.filter((t: Task) => t.record_type === 'demonstration'));
            }
          });
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const toggleTask = (taskId: string, passed: boolean) => {
    setTasks(prev => prev.map(t => t.id === taskId ? { ...t, is_completed: passed } : t));
  };

  const saveObservation = async () => {
    if (!record) return;
    setSaving(true);
    try {
      const task_results = tasks.map(t => ({ task_id: t.id, passed: t.is_completed }));
      const res = await axiosClient.post(`/training/record/${record.id}/phase4-observation`, {
        observation_notes: notes,
        task_results,
      });
      setScorePreview(res.data);
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const submitRecord = async () => {
    if (!record) return;
    setSubmitting(true);
    try {
      const res = await axiosClient.post(`/training/record/${record.id}/submit`);
      setSubmitResult({
        score: res.data.score,
        passed: res.data.passed,
        failed: res.data.failed_mandatory_topics ?? [],
      });
      setSubmitted(true);
    } catch (e: any) {
      console.error(e);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-8">
        <SectionHeader eyebrow="Phase 4" title="Practical Observation" />
        <SkeletonCard className="h-64" />
      </div>
    );
  }

  if (!record) {
    return (
      <div className="space-y-8">
        <SectionHeader eyebrow="Phase 4" title="Practical Observation" />
        <MotionCard hoverable={false}>
          <div className="text-center py-12 text-sm text-muted-foreground">
            <ClipboardList className="w-10 h-10 mx-auto mb-3 opacity-40" />
            No Phase 4 training session active today.
          </div>
        </MotionCard>
      </div>
    );
  }

  if (submitted && submitResult) {
    return (
      <div className="space-y-8">
        <SectionHeader eyebrow="Phase 4" title="Observation Complete" />
        <MotionCard hoverable={false}>
          <div className="text-center py-10 space-y-4">
            {submitResult.passed ? (
              <>
                <CheckCircle2 className="w-14 h-14 mx-auto text-success" />
                <p className="text-xl font-bold text-success">Passed</p>
                <p className="text-sm text-muted-foreground">
                  Score: {submitResult.score.toFixed(1)}% — {trainee?.name} has completed all 4 phases of training.
                </p>
              </>
            ) : (
              <>
                <AlertTriangle className="w-14 h-14 mx-auto text-danger" />
                <p className="text-xl font-bold text-danger">Did Not Pass</p>
                <p className="text-sm text-muted-foreground">
                  Score: {submitResult.score.toFixed(1)}% — A remediation session (Phase 5) has been generated.
                  Management has been notified.
                </p>
                {submitResult.failed.length > 0 && (
                  <div className="text-left mt-4 border border-danger/20 rounded-xl p-4 space-y-1">
                    <p className="text-xs font-semibold text-danger mb-2">Topics to remediate:</p>
                    {submitResult.failed.map(topic => (
                      <p key={topic} className="text-xs text-muted-foreground">• {topic}</p>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </MotionCard>
      </div>
    );
  }

  const mandatory = tasks.filter(t => t.is_mandatory);
  const optional = tasks.filter(t => !t.is_mandatory);
  const mandatoryPassed = mandatory.filter(t => t.is_completed).length;

  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow="Phase 4 — Practical Shadowing"
        title={`Observing ${trainee?.name ?? 'Trainee'}`}
        description="Mark each topic as observed correctly during the field session. All mandatory items must pass (90% threshold). Add notes below."
      />

      {/* Score preview */}
      {scorePreview && (
        <div className={`rounded-xl border p-4 flex items-center gap-4 ${
          scorePreview.would_pass ? 'border-success/30 bg-success/5' : 'border-warning/30 bg-warning/5'
        }`}>
          <div className="text-3xl font-bold">
            {scorePreview.score_preview.toFixed(1)}%
          </div>
          <div>
            <p className={`text-sm font-semibold ${scorePreview.would_pass ? 'text-success' : 'text-warning'}`}>
              {scorePreview.would_pass ? 'Would pass at current state' : 'Would not pass — more items needed'}
            </p>
            <p className="text-xs text-muted-foreground">
              {scorePreview.passed_mandatory}/{scorePreview.total_mandatory} mandatory items passed
            </p>
          </div>
        </div>
      )}

      {/* Mandatory tasks */}
      <MotionCard delay={0.05} hoverable={false}>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4">
          Mandatory ({mandatoryPassed}/{mandatory.length} passed)
        </p>
        <div className="space-y-2">
          {mandatory.map(task => (
            <div
              key={task.id}
              className={`flex items-start gap-3 p-3 rounded-lg border transition-colors cursor-pointer ${
                task.is_completed ? 'border-success/30 bg-success/5' : 'border-border hover:bg-accent'
              }`}
              onClick={() => toggleTask(task.id, !task.is_completed)}
            >
              {task.is_completed
                ? <CheckCircle2 className="w-5 h-5 text-success shrink-0 mt-0.5" />
                : <Circle className="w-5 h-5 text-muted-foreground shrink-0 mt-0.5" />
              }
              <div className="min-w-0">
                <p className="text-sm font-medium leading-snug">{task.topic_title}</p>
                {task.description && (
                  <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed line-clamp-2">
                    {task.description}
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </MotionCard>

      {/* Optional tasks */}
      {optional.length > 0 && (
        <MotionCard delay={0.1} hoverable={false}>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4">
            Optional ({optional.filter(t => t.is_completed).length}/{optional.length} passed)
          </p>
          <div className="space-y-2">
            {optional.map(task => (
              <div
                key={task.id}
                className={`flex items-start gap-3 p-3 rounded-lg border transition-colors cursor-pointer ${
                  task.is_completed ? 'border-success/30 bg-success/5' : 'border-border hover:bg-accent'
                }`}
                onClick={() => toggleTask(task.id, !task.is_completed)}
              >
                {task.is_completed
                  ? <CheckCircle2 className="w-5 h-5 text-success shrink-0 mt-0.5" />
                  : <Circle className="w-5 h-5 text-muted-foreground shrink-0 mt-0.5" />
                }
                <p className="text-sm leading-snug">{task.topic_title}</p>
              </div>
            ))}
          </div>
        </MotionCard>
      )}

      {/* Observation notes */}
      <MotionCard delay={0.15} hoverable={false}>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
          Observation Notes
        </p>
        <textarea
          value={notes}
          onChange={e => setNotes(e.target.value)}
          placeholder="Add any additional commentary about the DA's performance today..."
          rows={4}
          className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
      </MotionCard>

      {/* Actions */}
      <div className="flex gap-3">
        <button
          onClick={saveObservation}
          disabled={saving}
          className="btn-secondary flex items-center gap-2"
        >
          {saving ? 'Saving…' : 'Save & Preview Score'}
        </button>
        <button
          onClick={submitRecord}
          disabled={submitting || !scorePreview}
          className="btn-primary flex items-center gap-2"
          title={!scorePreview ? 'Save and preview score before submitting' : ''}
        >
          <Send className="w-4 h-4" />
          {submitting ? 'Submitting…' : 'Submit Final Record'}
        </button>
      </div>
      {!scorePreview && (
        <p className="text-xs text-muted-foreground">
          Save and preview the score before submitting.
        </p>
      )}
    </div>
  );
}
