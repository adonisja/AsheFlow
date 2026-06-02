import React, { useEffect, useState } from 'react';
import axiosClient from '../../api/axiosClient';
import { useAuth } from '../../contexts/AuthContext';
import NotificationBanner from '../../components/NotificationBanner';
import { getLocalYMD } from '../../utils/date';
import {
  Loader2, Users, ClipboardList, History, MessageSquare,
  AlertTriangle, Star, CheckCircle2, XCircle, RefreshCw,
  UserCheck, Calendar, ChevronDown, ChevronUp, Info, BarChart2,
} from 'lucide-react';
import TaskChecklist from '../../components/TrainerDashboard/TaskChecklist';
import ManagerComments from '../../components/TrainerDashboard/ManagerComments';
import ErrorBanner from '../../components/ui/ErrorBanner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tab = 'today' | 'history' | 'performance';

interface TodayData {
  record: any | null;
  trainee: { id: string; name: string } | null;
  tasks: any[];
  previous_trainer_comments: { comments: string; record_date: string; day_number: number } | null;
  manager_comments: string | null;
}

interface TraineeGroup {
  trainee: { id: string; name: string } | null;
  sessions: { record: any; tasks: any[] }[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------


const starRow = (rating: number) => (
  <span className="text-warning font-black text-sm">
    {'★'.repeat(rating)}{'☆'.repeat(5 - rating)}
  </span>
);

const taskCompletionBadge = (tasks: any[]) => {
  const total = tasks.length;
  const done = tasks.filter(t => t.is_completed).length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const color = pct === 100 ? 'text-success' : pct >= 60 ? 'text-warning' : 'text-danger';
  return <span className={`text-xs font-bold ${color}`}>{done}/{total}</span>;
};

// ---------------------------------------------------------------------------
// Previous Trainer Handoff Note
// ---------------------------------------------------------------------------

function HandoffNote({ data }: { data: { comments: string; record_date: string; day_number: number } }) {
  const [open, setOpen] = useState(true);
  return (
    <div className="card border-violet/30 bg-violet/5 space-y-3">
      <button
        className="flex items-center justify-between w-full text-left"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-2">
          <MessageSquare className="w-4 h-4 text-violet shrink-0" />
          <span className="text-sm font-semibold text-foreground">
            Handoff Note — Day {data.day_number} ({new Date(data.record_date + 'T00:00:00').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })})
          </span>
        </div>
        {open ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
      </button>
      {open && (
        <p className="text-sm text-foreground whitespace-pre-line leading-relaxed pl-6 border-l-2 border-violet/30 ml-1">
          {data.comments}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Today Tab
// ---------------------------------------------------------------------------

function TodayTab({
  data,
  trainerId,
  onRefresh,
}: {
  data: TodayData;
  trainerId: string;
  onRefresh: () => void;
}) {
  const [trainerNote, setTrainerNote] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  if (!data.record || !data.trainee) {
    return (
      <div className="card text-center py-20 flex flex-col items-center bg-accent/30 border-dashed">
        <div className="w-16 h-16 rounded-full bg-background flex items-center justify-center mb-4">
          <Users className="text-subtle w-8 h-8" />
        </div>
        <h2 className="text-xl font-semibold mb-2">No Trainee Assigned Today</h2>
        <p className="text-subtle max-w-sm mx-auto text-sm">
          You don't have a trainee assigned to your truck today. Check back after dispatch runs.
        </p>
      </div>
    );
  }

  const { record, trainee, tasks, previous_trainer_comments, manager_comments } = data;

  // Inject tasks into record shape for TaskChecklist
  const recordWithTasks = { ...record, tasks };

  const saveTrainerNote = async () => {
    if (!trainerNote.trim()) return;
    setIsSaving(true);
    try {
      await axiosClient.post(`/training/trainee/${trainee.id}/trainer-comments`, {
        comments: trainerNote,
      });
      setSaved(true);
      setTrainerNote('');
      setTimeout(() => { setSaved(false); onRefresh(); }, 1200);
    } catch (err) {
      console.error('Failed to save trainer note:', err);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Trainee header card */}
      <div className="card-elevated border-primary/20 flex items-center gap-4">
        <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-primary/10 shrink-0">
          <UserCheck className="w-6 h-6 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="font-bold text-lg text-foreground">{trainee.name}</p>
          <p className="text-sm text-muted-foreground">
            Training Day {record.current_day_number}
            {record.is_locked && (
              <span className="ml-2 text-xs text-warning font-medium">(Record locked)</span>
            )}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-subtle uppercase tracking-wider">Today</p>
          <p className="text-sm font-semibold text-foreground">
            {new Date(getLocalYMD() + 'T00:00:00').toLocaleDateString('en-US', {
              weekday: 'long', month: 'short', day: 'numeric',
            })}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left col: handoff note + task checklist */}
        <div className="lg:col-span-2 space-y-4">
          {previous_trainer_comments && (
            <HandoffNote data={previous_trainer_comments} />
          )}

          <TaskChecklist record={recordWithTasks} isReadOnly={record.is_locked} />

          {/* Trainer's own note for this session */}
          {!record.is_locked && (
            <div className="card space-y-3">
              <div className="flex items-center gap-2 border-b border-border pb-3">
                <MessageSquare className="w-4 h-4 text-primary" />
                <h3 className="font-semibold text-foreground">Your Handoff Note</h3>
              </div>
              <p className="text-xs text-subtle">
                Leave notes for the next trainer who works with {trainee.name}. These are visible to other trainers and management.
              </p>
              {record.trainer_comments && (
                <div className="bg-accent/50 p-3 rounded-xl text-sm text-foreground whitespace-pre-line border border-border">
                  <span className="text-xs text-muted-foreground font-semibold uppercase tracking-wider block mb-1">Already on file</span>
                  {record.trainer_comments}
                </div>
              )}
              <textarea
                className="w-full bg-background border border-input rounded-xl p-3 text-sm focus:ring-1 focus:ring-primary focus:border-primary transition-colors min-h-[90px] resize-y"
                placeholder={record.trainer_comments ? 'Append additional notes...' : 'Write notes for the next trainer...'}
                value={trainerNote}
                onChange={e => setTrainerNote(e.target.value)}
                disabled={isSaving}
              />
              <button
                onClick={saveTrainerNote}
                disabled={!trainerNote.trim() || isSaving}
                className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-semibold hover:bg-primary/90 transition-colors disabled:opacity-50"
              >
                {isSaving ? <Loader2 className="w-4 h-4 animate-spin" /> : <MessageSquare className="w-4 h-4" />}
                {isSaving ? 'Saving...' : saved ? 'Saved!' : 'Save Note'}
              </button>
            </div>
          )}
        </div>

        {/* Right col: management notes */}
        <div>
          <ManagerComments record={{ ...record, manager_comments }} traineeId={trainee.id} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// History Tab
// ---------------------------------------------------------------------------

function SessionCard({ session }: { session: { record: any; tasks: any[] } }) {
  const [open, setOpen] = useState(false);
  const { record, tasks } = session;
  const debtTasks = tasks.filter(t => t.is_training_debt);
  const hasEscalated = tasks.some(t => t.is_escalated && !t.is_completed);

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button
        className="w-full flex items-center justify-between px-4 py-3 bg-accent/40 hover:bg-accent/70 transition-colors text-left"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-3">
          {hasEscalated && <AlertTriangle className="w-3.5 h-3.5 text-warning shrink-0" />}
          <span className="font-semibold text-sm text-foreground">
            Day {record.current_day_number} &middot;{' '}
            {new Date(record.record_date + 'T00:00:00').toLocaleDateString('en-US', {
              weekday: 'short', month: 'short', day: 'numeric',
            })}
          </span>
          {debtTasks.length > 0 && (
            <span className="text-xs text-danger font-medium bg-danger/10 px-1.5 py-0.5 rounded">
              {debtTasks.length} debt
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {taskCompletionBadge(tasks)}
          {record.trainer_rating != null && starRow(record.trainer_rating)}
          {open ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
        </div>
      </button>

      {open && (
        <div className="px-4 py-4 space-y-4 bg-background">
          {/* Tasks */}
          <div className="space-y-2">
            {tasks.map(task => (
              <div key={task.id} className="flex items-start gap-2.5 text-sm">
                {task.is_completed
                  ? <CheckCircle2 className="w-4 h-4 text-success shrink-0 mt-0.5" />
                  : <XCircle className={`w-4 h-4 shrink-0 mt-0.5 ${task.is_training_debt ? 'text-danger' : 'text-muted-foreground'}`} />}
                <span className={task.is_completed ? 'text-subtle line-through' : task.is_training_debt ? 'text-danger font-medium' : 'text-foreground'}>
                  {task.topic_title}
                </span>
              </div>
            ))}
          </div>

          {/* Trainer's own note */}
          {record.trainer_comments && (
            <div className="bg-violet/5 p-3 rounded-xl border border-violet/20 text-sm space-y-1">
              <span className="text-xs text-violet font-bold uppercase tracking-wider block">Your Note</span>
              <p className="text-foreground whitespace-pre-line">{record.trainer_comments}</p>
            </div>
          )}

          {/* Trainee's review */}
          {record.trainer_rating != null && (
            <div className="bg-warning/5 p-3 rounded-xl border border-warning/20 text-sm space-y-1">
              <div className="flex items-center gap-2">
                <Star className="w-3.5 h-3.5 text-warning" />
                <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Trainee Review</span>
              </div>
              <div>{starRow(record.trainer_rating)}</div>
              {record.trainee_comments && (
                <p className="text-foreground text-xs">{record.trainee_comments}</p>
              )}
            </div>
          )}

          {/* Manager note */}
          {record.manager_comments && (
            <div className="bg-info/5 p-3 rounded-xl border border-info/20 text-sm space-y-1">
              <span className="text-xs text-info font-bold uppercase tracking-wider block">Manager Note</span>
              <p className="text-foreground whitespace-pre-line">{record.manager_comments}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function HistoryTab({ trainerId }: { trainerId: string }) {
  const [groups, setGroups] = useState<TraineeGroup[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axiosClient.get(`/training/trainer/${trainerId}/history`)
      .then(res => setGroups(res.data))
      .catch(() => setError('Failed to load training history.'))
      .finally(() => setIsLoading(false));
  }, [trainerId]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="w-6 h-6 text-primary animate-spin" />
      </div>
    );
  }

  if (error) return <ErrorBanner message={error} />;

  if (groups.length === 0) {
    return (
      <div className="card text-center py-16 flex flex-col items-center bg-accent/30 border-dashed">
        <div className="w-14 h-14 rounded-full bg-background flex items-center justify-center mb-3">
          <History className="w-7 h-7 text-subtle" />
        </div>
        <p className="font-semibold text-foreground">No training history yet</p>
        <p className="text-subtle text-sm mt-1">Your completed training sessions will appear here.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-subtle">
        <Info className="w-4 h-4 shrink-0" />
        <span>{groups.length} trainee{groups.length !== 1 ? 's' : ''} trained across all time</span>
      </div>

      {groups.map(group => {
        const id = group.trainee?.id ?? 'unknown';
        const isOpen = expanded === id;
        const sessions = group.sessions;
        const totalDays = sessions.length;
        const allTasks = sessions.flatMap(s => s.tasks);
        const completionRate = allTasks.length > 0
          ? Math.round((allTasks.filter(t => t.is_completed).length / allTasks.length) * 100)
          : 0;
        const avgRating = (() => {
          const rated = sessions.filter(s => s.record.trainer_rating != null);
          if (!rated.length) return null;
          return (rated.reduce((sum, s) => sum + s.record.trainer_rating, 0) / rated.length).toFixed(1);
        })();

        return (
          <div key={id} className="card-elevated border hover:border-primary/30 transition-colors">
            {/* Trainee header */}
            <button
              className="w-full flex items-start justify-between gap-4 text-left"
              onClick={() => setExpanded(isOpen ? null : id)}
            >
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                  <UserCheck className="w-4 h-4 text-primary" />
                </div>
                <div>
                  <p className="font-semibold text-foreground">{group.trainee?.name ?? 'Unknown Trainee'}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {totalDays} session{totalDays !== 1 ? 's' : ''} &middot; {completionRate}% task completion
                    {avgRating && <> &middot; avg {avgRating}★</>}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0 mt-1">
                <span className="text-xs text-muted-foreground hidden sm:block">
                  Last: {new Date(sessions[0].record.record_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                </span>
                {isOpen ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
              </div>
            </button>

            {/* Session list */}
            {isOpen && (
              <div className="mt-4 space-y-2 border-t border-border pt-4">
                {sessions.map(session => (
                  <SessionCard key={session.record.id} session={session} />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// My Performance Tab
// ---------------------------------------------------------------------------
function MyPerformanceTab() {
  const [summary, setSummary] = useState<any>(null);
  const [marks, setMarks]     = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      axiosClient.get('/trainer-marks/mine/summary'),
      axiosClient.get('/trainer-marks/mine'),
    ])
      .then(([sRes, mRes]) => {
        setSummary(sRes.data);
        setMarks(mRes.data);
      })
      .catch((e) => { console.error('Failed to load trainer marks:', e); })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex justify-center py-16 opacity-50">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-3 gap-4">
          <div className={`card-elevated text-center ${summary.underperforming ? 'border-danger/40' : ''}`}>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Total Marks</p>
            <p className={`text-3xl font-bold ${summary.total_marks > 0 ? 'text-warning' : 'text-success'}`}>
              {summary.total_marks}
            </p>
          </div>
          <div className="card-elevated text-center">
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Trainees Affected</p>
            <p className="text-3xl font-bold text-foreground">{summary.distinct_trainees_with_marks}</p>
          </div>
          <div className={`card-elevated text-center ${summary.underperforming ? 'border-danger/60 bg-danger/5' : ''}`}>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Status</p>
            <p className={`text-sm font-bold mt-1 ${summary.underperforming ? 'text-danger' : 'text-success'}`}>
              {summary.underperforming ? 'Under Review' : 'Good Standing'}
            </p>
          </div>
        </div>
      )}

      {summary?.underperforming && (
        <div className="flex items-start gap-2 p-3 rounded-xl bg-danger/10 border border-danger/30">
          <AlertTriangle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
          <p className="text-sm text-danger">
            You have marks filed across {summary.distinct_trainees_with_marks} or more trainees. Management has been flagged for review. Speak with your supervisor if you have questions.
          </p>
        </div>
      )}

      {marks.length === 0 ? (
        <div className="card text-center py-10">
          <CheckCircle2 className="w-10 h-10 text-success mx-auto mb-3 opacity-60" />
          <p className="text-sm font-medium text-foreground">No marks on record</p>
          <p className="text-xs text-subtle mt-1">Marks are filed by management when performance concerns are noted.</p>
        </div>
      ) : (
        <div className="card">
          <p className="text-xs text-muted-foreground uppercase tracking-wider mb-3">Mark History</p>
          <div className="space-y-2">
            {marks.map((m: any) => {
              const isOpen = expanded === m.id;
              return (
                <div key={m.id} className="rounded-xl border border-border overflow-hidden">
                  <button
                    className="w-full flex items-start gap-3 px-3 py-3 hover:bg-accent/40 transition-colors text-left"
                    onClick={() => setExpanded(isOpen ? null : m.id)}
                  >
                    <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground">{m.reason}</p>
                      <p className="text-xs text-subtle mt-0.5">
                        Trainee: {m.trainee?.name ?? '—'}
                        {m.phase && ` · Phase ${m.phase}`}
                        {m.record_date && ` · ${m.record_date}`}
                      </p>
                    </div>
                    {isOpen ? <ChevronUp className="w-4 h-4 text-muted-foreground shrink-0" /> : <ChevronDown className="w-4 h-4 text-muted-foreground shrink-0" />}
                  </button>
                  {isOpen && m.debt_chain_context && (
                    <div className="px-3 pb-3 pt-1 border-t border-border/50">
                      <p className="text-xs text-subtle italic">{m.debt_chain_context}</p>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default function TrainerDashboard() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>('today');
  const [todayData, setTodayData] = useState<TodayData | null>(null);
  const [trainerId, setTrainerId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchToday = async () => {
    try {
      const res = await axiosClient.get('/training/trainer/today');
      setTodayData(res.data);
    } catch {
      setError('Failed to load today\'s training session.');
    }
  };

  const fetchCallerId = async () => {
    try {
      const res = await axiosClient.get('/employees/me');
      setTrainerId(res.data.id);
    } catch {
      setError('Failed to identify trainer account.');
    }
  };

  const load = async () => {
    setIsLoading(true);
    setError(null);
    await Promise.all([fetchToday(), fetchCallerId()]);
    setIsLoading(false);
  };

  useEffect(() => { load(); }, []);

  const tabs = [
    { key: 'today' as Tab,       label: "Today's Session", icon: ClipboardList },
    { key: 'history' as Tab,     label: 'My History',      icon: History },
    { key: 'performance' as Tab, label: 'My Performance',  icon: BarChart2 },
  ];

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 opacity-50">
        <Loader2 className="w-8 h-8 text-primary animate-spin mb-4" />
        <p className="text-sm font-medium">Loading trainer dashboard...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="page-title">Trainer Dashboard</h1>
          <p className="text-subtle mt-1">
            {todayData?.trainee
              ? `Paired with ${todayData.trainee.name} today`
              : 'No pairing today'}
          </p>
        </div>
        <button onClick={load} className="btn-ghost text-muted-foreground flex items-center gap-2 text-sm">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>
      {trainerId && <NotificationBanner employeeId={trainerId} />}

      <ErrorBanner message={error} />

      {/* Tab bar */}
      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 w-fit">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === key
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'today' && todayData && (
        <TodayTab data={todayData} trainerId={trainerId ?? ''} onRefresh={fetchToday} />
      )}

      {tab === 'history' && trainerId && (
        <HistoryTab trainerId={trainerId} />
      )}

      {tab === 'performance' && (
        <MyPerformanceTab />
      )}
    </div>
  );
}
