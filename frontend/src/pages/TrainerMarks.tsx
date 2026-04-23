import React, { useEffect, useState } from 'react';
import { AlertTriangle, Star, TrendingDown, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import MotionCard from '../components/ui/MotionCard';
import { SkeletonCard } from '../components/ui/Skeleton';

interface TrainerSummary {
  trainer: { id: string; name: string } | null;
  total_marks: number;
  distinct_trainees_with_marks: number;
  underperforming: boolean;
}

interface Mark {
  id: string;
  trainer: { id: string; name: string } | null;
  trainee: { id: string; name: string } | null;
  phase: number | null;
  record_date: string | null;
  reason: string;
  debt_originated: boolean;
  debt_chain_context: string | null;
  created_at: string;
}

const REASON_LABEL: Record<string, string> = {
  phase_not_closed: 'Phase not closed',
  submitted_late: 'Submitted late',
};

export default function TrainerMarks() {
  const [summaries, setSummaries] = useState<TrainerSummary[]>([]);
  const [marks, setMarks] = useState<Mark[]>([]);
  const [selectedTrainerId, setSelectedTrainerId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [expandedMark, setExpandedMark] = useState<string | null>(null);

  const loadSummary = () => {
    setLoading(true);
    axiosClient.get('/trainer-marks/summary')
      .then(r => setSummaries(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  const loadMarks = (trainerId: string | null) => {
    const url = trainerId
      ? `/trainer-marks/trainer/${trainerId}`
      : '/trainer-marks/';
    axiosClient.get(url)
      .then(r => setMarks(r.data))
      .catch(console.error);
  };

  useEffect(() => { loadSummary(); loadMarks(null); }, []);

  useEffect(() => { loadMarks(selectedTrainerId); }, [selectedTrainerId]);

  const underperforming = summaries.filter(s => s.underperforming);

  if (loading) {
    return (
      <div className="space-y-8">
        <SectionHeader eyebrow="Management" title="Trainer Performance Marks" />
        <div className="grid grid-cols-1 gap-4">
          {Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} className="h-20" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <SectionHeader
        eyebrow="Management"
        title="Trainer Performance Marks"
        description="Accountability records for training phase closures. Marks are only issued when a trainer fails to close their phase with no inherited debt."
        actions={
          <button onClick={() => { loadSummary(); loadMarks(selectedTrainerId); }} className="btn-ghost flex items-center gap-2 text-sm">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      {/* Underperforming alert banner */}
      {underperforming.length > 0 && (
        <div className="rounded-xl border border-danger/30 bg-danger/5 p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-danger mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-semibold text-danger">
              {underperforming.length} trainer{underperforming.length > 1 ? 's' : ''} flagged as underperforming
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Marks across 3 or more distinct trainees. Review their records below.
            </p>
          </div>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {summaries.map(s => (
          <button
            key={s.trainer?.id}
            onClick={() => setSelectedTrainerId(
              selectedTrainerId === s.trainer?.id ? null : (s.trainer?.id ?? null)
            )}
            className={`text-left rounded-xl border p-4 transition-colors ${
              selectedTrainerId === s.trainer?.id
                ? 'border-primary bg-primary/5'
                : s.underperforming
                  ? 'border-danger/40 bg-danger/5 hover:bg-danger/10'
                  : 'border-border hover:bg-accent'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium text-sm">{s.trainer?.name ?? 'Unknown'}</span>
              {s.underperforming && (
                <span className="badge badge-error text-[10px]">
                  <TrendingDown className="w-3 h-3 mr-1" /> Underperforming
                </span>
              )}
            </div>
            <div className="flex gap-4 text-xs text-muted-foreground">
              <span><span className="font-semibold text-foreground">{s.total_marks}</span> mark{s.total_marks !== 1 ? 's' : ''}</span>
              <span><span className="font-semibold text-foreground">{s.distinct_trainees_with_marks}</span> trainee{s.distinct_trainees_with_marks !== 1 ? 's' : ''}</span>
            </div>
          </button>
        ))}

        {summaries.length === 0 && (
          <div className="col-span-full text-center py-10 text-sm text-muted-foreground">
            <Star className="w-8 h-8 mx-auto mb-2 text-success" />
            No trainer marks on record. All phases closed on time.
          </div>
        )}
      </div>

      {/* Mark detail table */}
      {marks.length > 0 && (
        <MotionCard delay={0.05} hoverable={false}>
          <div className="mb-4 flex items-center justify-between">
            <p className="text-sm font-medium">
              {selectedTrainerId
                ? `Marks for ${summaries.find(s => s.trainer?.id === selectedTrainerId)?.trainer?.name ?? 'trainer'}`
                : 'All marks'}
            </p>
            {selectedTrainerId && (
              <button
                onClick={() => setSelectedTrainerId(null)}
                className="text-xs text-muted-foreground hover:text-foreground"
              >
                Show all
              </button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                  <th className="pb-3 pr-4">Trainer</th>
                  <th className="pb-3 pr-4">Trainee</th>
                  <th className="pb-3 pr-4">Phase</th>
                  <th className="pb-3 pr-4">Date</th>
                  <th className="pb-3 pr-4">Reason</th>
                  <th className="pb-3">Context</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {marks.map(m => (
                  <React.Fragment key={m.id}>
                    <tr className="group">
                      <td className="py-3 pr-4 font-medium">{m.trainer?.name ?? '—'}</td>
                      <td className="py-3 pr-4 text-muted-foreground">{m.trainee?.name ?? '—'}</td>
                      <td className="py-3 pr-4">
                        <span className="badge bg-accent text-foreground">Phase {m.phase ?? '?'}</span>
                      </td>
                      <td className="py-3 pr-4 text-xs text-muted-foreground whitespace-nowrap">
                        {m.record_date ?? '—'}
                      </td>
                      <td className="py-3 pr-4">
                        <span className="badge badge-warning text-[10px]">
                          {REASON_LABEL[m.reason] ?? m.reason}
                        </span>
                      </td>
                      <td className="py-3">
                        {m.debt_chain_context ? (
                          <button
                            onClick={() => setExpandedMark(expandedMark === m.id ? null : m.id)}
                            className="flex items-center gap-1 text-xs text-primary hover:underline"
                          >
                            Context {expandedMark === m.id ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                          </button>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                    {expandedMark === m.id && m.debt_chain_context && (
                      <tr>
                        <td colSpan={6} className="pb-3 pt-0 px-0">
                          <div className="mx-0 rounded-lg bg-accent/50 p-3 text-xs text-muted-foreground leading-relaxed">
                            {m.debt_chain_context}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </MotionCard>
      )}
    </div>
  );
}
