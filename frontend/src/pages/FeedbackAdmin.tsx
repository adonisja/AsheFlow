import React, { useEffect, useState } from 'react';
import axiosClient from '../api/axiosClient';
import { MessageSquare, Bug, Lightbulb, RefreshCw, CheckCircle2 } from 'lucide-react';
import SectionHeader from '../components/ui/SectionHeader';
import MotionCard from '../components/ui/MotionCard';
import { SkeletonCard } from '../components/ui/Skeleton';
import ErrorBanner from '../components/ui/ErrorBanner';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { useConfirm } from '../hooks/useConfirm';

type FeedbackType = 'bug' | 'feature_request' | 'general';
type FeedbackStatus = 'new' | 'in_progress' | 'resolved';

interface Feedback {
  id: string;
  employee_id: string | null;
  sender_name: string | null;
  type: FeedbackType;
  message: string;
  status: FeedbackStatus;
  created_at: string;
}

const TYPE_ICON: Record<FeedbackType, React.ReactNode> = {
  bug:             <Bug className="w-3.5 h-3.5" />,
  feature_request: <Lightbulb className="w-3.5 h-3.5" />,
  general:         <MessageSquare className="w-3.5 h-3.5" />,
};

const TYPE_LABEL: Record<FeedbackType, string> = {
  bug:             'Bug Report',
  feature_request: 'Feature Request',
  general:         'General',
};

const STATUS_BADGE: Record<FeedbackStatus, string> = {
  new:         'badge-info',
  in_progress: 'badge-warning',
  resolved:    'badge-success',
};

const FILTERS: { label: string; value: FeedbackStatus | 'all' }[] = [
  { label: 'All',         value: 'all' },
  { label: 'New',         value: 'new' },
  { label: 'In Progress', value: 'in_progress' },
  { label: 'Resolved',    value: 'resolved' },
];

export default function FeedbackAdmin() {
  const { confirmState, confirm, cancelConfirm } = useConfirm();
  const [feedback, setFeedback] = useState<Feedback[]>([]);
  const [filter, setFilter] = useState<FeedbackStatus | 'all'>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchFeedback = () => {
    setLoading(true);
    setError(null);
    axiosClient.get('/feedback/?limit=200')
      .then(r => setFeedback(r.data))
      .catch(() => setError('Failed to load feedback. Please refresh.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchFeedback(); }, []);

  const updateStatus = async (id: string, newStatus: FeedbackStatus) => {
    const labels: Record<FeedbackStatus, string> = { new: 'New', in_progress: 'In Progress', resolved: 'Resolved' };
    const ok = await confirm({
      title: 'Update Feedback Status',
      message: `Mark this feedback as "${labels[newStatus]}"?`,
      confirmLabel: 'Update',
      variant: newStatus === 'resolved' ? 'default' : 'warning',
    });
    if (!ok) return;
    axiosClient.patch(`/feedback/${id}/status`, { status: newStatus })
      .then(r => setFeedback(prev => prev.map(f => f.id === id ? r.data : f)))
      .catch(() => setError('Failed to update feedback status.'));
  };

  const visible = filter === 'all' ? feedback : feedback.filter(f => f.status === filter);

  const counts = {
    all:         feedback.length,
    new:         feedback.filter(f => f.status === 'new').length,
    in_progress: feedback.filter(f => f.status === 'in_progress').length,
    resolved:    feedback.filter(f => f.status === 'resolved').length,
  };

  if (loading) {
    return (
      <div className="space-y-8">
        <SectionHeader eyebrow="Admin" title="Feedback Inbox" />
        <div className="grid grid-cols-1 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} className="h-24" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <ConfirmDialog {...confirmState} onCancel={cancelConfirm} />
      <SectionHeader
        eyebrow="Admin"
        title="Feedback Inbox"
        description="Review and action feedback submitted by employees."
        actions={
          <button onClick={fetchFeedback} className="btn-ghost flex items-center gap-2 text-sm">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      <ErrorBanner message={error} />

      {/* Filter + counts */}
      <div className="flex items-center gap-2 flex-wrap">
        {FILTERS.map(f => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-xl border font-medium transition-colors ${
              filter === f.value
                ? 'bg-primary text-primary-foreground border-primary'
                : 'border-border text-muted-foreground hover:text-foreground hover:bg-accent'
            }`}
          >
            {f.label}
            <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-bold ${
              filter === f.value ? 'bg-primary-foreground/20' : 'bg-accent'
            }`}>
              {counts[f.value]}
            </span>
          </button>
        ))}
      </div>

      {/* Table */}
      <MotionCard delay={0.05} hoverable={false}>
        {visible.length === 0 ? (
          <div className="text-center py-12 opacity-60">
            <CheckCircle2 className="w-10 h-10 mb-3 text-success mx-auto" />
            <p className="text-sm font-medium">
              {filter === 'all' ? 'No feedback submitted yet.' : `No ${filter.replace('_', ' ')} feedback.`}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                  <th className="pb-3 pr-4">Type</th>
                  <th className="pb-3 pr-4">Message</th>
                  <th className="pb-3 pr-4 hidden sm:table-cell">From</th>
                  <th className="pb-3 pr-4">Submitted</th>
                  <th className="pb-3 pr-4">Status</th>
                  <th className="pb-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {visible.map(f => {
                  const daysSince = Math.floor(
                    (Date.now() - new Date(f.created_at).getTime()) / 86_400_000
                  );
                  const ageLabel = daysSince === 0 ? 'Today' : `${daysSince}d ago`;
                  const ageCls = daysSince >= 7 ? 'text-danger' : daysSince >= 3 ? 'text-warning' : 'text-muted-foreground';

                  return (
                    <tr key={f.id} className="group">
                      <td className="py-3 pr-4">
                        <span className="badge bg-accent text-foreground gap-1.5 whitespace-nowrap">
                          {TYPE_ICON[f.type]}
                          {TYPE_LABEL[f.type]}
                        </span>
                      </td>
                      <td className="py-3 pr-4 max-w-md">
                        <p className="text-foreground leading-snug line-clamp-2">{f.message}</p>
                      </td>
                      <td className="py-3 pr-4 hidden sm:table-cell text-xs text-muted-foreground whitespace-nowrap">
                        {f.sender_name ?? <span className="italic">Anonymous</span>}
                      </td>
                      <td className={`py-3 pr-4 text-xs whitespace-nowrap ${ageCls}`}>
                        {ageLabel}
                      </td>
                      <td className="py-3 pr-4">
                        <span className={`badge ${STATUS_BADGE[f.status]} capitalize`}>
                          {f.status.replace('_', ' ')}
                        </span>
                      </td>
                      <td className="py-3">
                        <div className="flex items-center gap-1">
                          {f.status === 'new' && (
                            <button
                              onClick={() => updateStatus(f.id, 'in_progress')}
                              className="text-xs px-2.5 py-1 rounded-lg border border-warning/40 text-warning hover:bg-warning/10 transition-colors whitespace-nowrap"
                            >
                              In Progress
                            </button>
                          )}
                          {f.status !== 'resolved' && (
                            <button
                              onClick={() => updateStatus(f.id, 'resolved')}
                              className="text-xs px-2.5 py-1 rounded-lg border border-success/40 text-success hover:bg-success/10 transition-colors"
                            >
                              Resolve
                            </button>
                          )}
                          {f.status === 'resolved' && (
                            <button
                              onClick={() => updateStatus(f.id, 'new')}
                              className="text-xs px-2.5 py-1 rounded-lg border border-border text-muted-foreground hover:bg-accent transition-colors"
                            >
                              Reopen
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </MotionCard>
    </div>
  );
}
