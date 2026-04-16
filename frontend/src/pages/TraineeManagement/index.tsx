import React, { useEffect, useState } from 'react';
import axiosClient from '../../api/axiosClient';
import {
  Users, Loader2, AlertTriangle, RefreshCw, ChevronRight,
  X, Calendar, Star, ClipboardList, UserCheck,
} from 'lucide-react';
import TaskChecklist from '../../components/TrainerDashboard/TaskChecklist';
import ManagerComments from '../../components/TrainerDashboard/ManagerComments';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Tab = 'today' | 'escalated' | 'history';

interface ActiveRecord {
  record: any;
  trainee: { id: string; name: string } | null;
  trainer: { id: string; name: string } | null;
  progress: { total: number; completed: number };
}

interface EscalatedRecord {
  trainee: { id: string; name: string } | null;
  trainer: { id: string; name: string } | null;
  record: any;
  escalated_tasks: { id: string; topic_title: string; description: string; debt_age: number }[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const getLocalYMD = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const progressColor = (completed: number, total: number) => {
  if (total === 0) return 'bg-accent';
  const pct = completed / total;
  if (pct === 1) return 'bg-success';
  if (pct >= 0.5) return 'bg-warning';
  return 'bg-primary';
};

// ---------------------------------------------------------------------------
// Today's Pairings Tab
// ---------------------------------------------------------------------------

function TodayTab({
  activeRecords,
  onSelectTrainee,
}: {
  activeRecords: ActiveRecord[];
  onSelectTrainee: (id: string, name: string) => void;
}) {
  if (activeRecords.length === 0) {
    return (
      <div className="card text-center py-20 flex flex-col items-center justify-center bg-accent/30 border-dashed">
        <div className="w-16 h-16 rounded-full bg-background flex items-center justify-center mb-4">
          <Users className="text-subtle w-8 h-8" />
        </div>
        <h2 className="text-xl font-semibold mb-2">No Active Pairings</h2>
        <p className="text-subtle max-w-sm mx-auto">
          Dispatch has not mapped any trainees to trucks today, or dispatch hasn't run yet.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {activeRecords.map(act => {
        const { completed, total } = act.progress;
        return (
          <button
            key={act.record.id}
            className="card-elevated border hover:border-primary/50 transition-colors text-left w-full"
            onClick={() => onSelectTrainee(act.trainee?.id ?? '', act.trainee?.name ?? 'Unknown')}
          >
            {/* Header row */}
            <div className="flex justify-between items-start mb-3">
              <span className="bg-primary/10 text-primary font-bold text-xs px-2 py-1 rounded-md uppercase tracking-wider">
                Day {act.record.current_day_number}
              </span>
              <span className="text-xs text-muted-foreground font-medium">
                {completed}/{total} tasks
              </span>
            </div>

            {/* Trainee name */}
            <p className="font-semibold text-base text-foreground mb-1">
              {act.trainee?.name ?? 'Unknown Trainee'}
            </p>

            {/* Trainer — prominent, always shown */}
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground mb-3">
              <UserCheck className="w-3.5 h-3.5 shrink-0" />
              <span>
                {act.trainer
                  ? <span className="font-medium text-foreground">{act.trainer.name}</span>
                  : <span className="italic text-subtle">No trainer assigned</span>}
              </span>
            </div>

            {/* Progress bar */}
            <div className="w-full bg-accent rounded-full h-1.5">
              <div
                className={`h-1.5 rounded-full transition-all ${progressColor(completed, total)}`}
                style={{ width: total > 0 ? `${(completed / total) * 100}%` : '0%' }}
              />
            </div>

            <div className="flex items-center justify-end mt-3 text-xs text-primary font-medium gap-1">
              View history <ChevronRight className="w-3.5 h-3.5" />
            </div>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Escalated Trainees Tab
// ---------------------------------------------------------------------------

function EscalatedTab({
  escalated,
  onSelectTrainee,
}: {
  escalated: EscalatedRecord[];
  onSelectTrainee: (id: string, name: string) => void;
}) {
  if (escalated.length === 0) {
    return (
      <div className="card text-center py-16 flex flex-col items-center bg-accent/30 border-dashed">
        <div className="w-14 h-14 rounded-full bg-success/10 flex items-center justify-center mb-3">
          <UserCheck className="w-7 h-7 text-success" />
        </div>
        <p className="font-semibold text-foreground">No escalated trainees</p>
        <p className="text-subtle text-sm mt-1">All trainees are on track.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {escalated.map(entry => (
        <div
          key={entry.record.id}
          className="card border-warning/40 bg-warning/5 space-y-4"
        >
          {/* Header */}
          <div className="flex items-start justify-between gap-4 flex-wrap">
            <div>
              <p className="font-semibold text-foreground text-base">
                {entry.trainee?.name ?? 'Unknown Trainee'}
              </p>
              <div className="flex items-center gap-1.5 text-sm text-muted-foreground mt-0.5">
                <UserCheck className="w-3.5 h-3.5 shrink-0" />
                <span>
                  Trainer:{' '}
                  {entry.trainer
                    ? <span className="font-medium text-foreground">{entry.trainer.name}</span>
                    : <span className="italic text-subtle">Unassigned</span>}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold text-warning bg-warning/15 border border-warning/30 px-2 py-1 rounded-lg">
                {entry.escalated_tasks.length} escalated task{entry.escalated_tasks.length !== 1 ? 's' : ''}
              </span>
              <button
                onClick={() => onSelectTrainee(entry.trainee?.id ?? '', entry.trainee?.name ?? '')}
                className="text-xs text-primary hover:underline flex items-center gap-1"
              >
                Full history <ChevronRight className="w-3 h-3" />
              </button>
            </div>
          </div>

          {/* Escalated task list */}
          <ul className="space-y-2">
            {entry.escalated_tasks.map(task => (
              <li key={task.id} className="flex items-start gap-3 text-sm">
                <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />
                <div>
                  <p className="font-medium text-foreground">{task.topic_title}</p>
                  {task.description && (
                    <p className="text-xs text-subtle mt-0.5">{task.description}</p>
                  )}
                  <p className="text-xs text-warning mt-0.5 font-medium">
                    Unresolved for {task.debt_age} dispatch day{task.debt_age !== 1 ? 's' : ''}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trainee History Drilldown
// ---------------------------------------------------------------------------

function HistoryView({
  traineeId,
  traineeName,
  allTrainees,
  onClose,
  onSelectTrainee,
}: {
  traineeId: string;
  traineeName: string;
  allTrainees: any[];
  onClose: () => void;
  onSelectTrainee: (id: string, name: string) => void;
}) {
  const [records, setRecords] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!traineeId) return;
    setLoading(true);
    axiosClient.get(`/training/trainee/${traineeId}`)
      .then(res => setRecords(res.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [traineeId]);

  const sorted = [...records].sort(
    (a, b) => new Date(b.record_date).getTime() - new Date(a.record_date).getTime()
  );
  const todayStr = getLocalYMD();
  const todayRecord = sorted.find(r => r.record_date === todayStr);
  const pastRecords = sorted.filter(r => r.record_date !== todayStr);

  return (
    <div className="space-y-6">
      {/* Drilldown header */}
      <div className="flex items-center justify-between gap-4 border-b border-border pb-4">
        <div className="flex items-center gap-3">
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
            title="Back to overview"
          >
            <X className="w-4 h-4" />
          </button>
          <div>
            <h2 className="text-lg font-semibold text-foreground">{traineeName}</h2>
            <p className="text-xs text-subtle">Training history</p>
          </div>
        </div>

        {/* Switch trainee without going back */}
        <select
          className="border border-input rounded-xl p-2 bg-background text-sm focus:ring-1 focus:ring-primary focus:border-primary"
          value={traineeId}
          onChange={e => {
            const selected = allTrainees.find(t => t.id === e.target.value);
            if (selected) onSelectTrainee(selected.id, selected.name ?? selected.first_name ?? '');
          }}
        >
          {allTrainees.map(t => (
            <option key={t.id} value={t.id}>{t.name ?? t.first_name}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="w-6 h-6 text-primary animate-spin" />
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: today's tasks + history */}
          <div className="lg:col-span-2 space-y-6">
            {todayRecord ? (
              <TaskChecklist record={todayRecord} isReadOnly={true} />
            ) : (
              <div className="card text-center text-subtle py-12 border-dashed border-2 bg-accent/30">
                <p className="text-lg font-medium mb-1 text-foreground">No Dispatch Today</p>
                <p className="text-sm">Not paired via active dispatch for today.</p>
              </div>
            )}

            {/* Past records */}
            <div className="card">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-lg font-semibold flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-primary" /> Progress Log
                </h2>
                <span className="text-sm px-2 py-1 bg-primary/10 text-primary font-medium rounded-lg">
                  {pastRecords.length} completed day{pastRecords.length !== 1 ? 's' : ''}
                </span>
              </div>

              {pastRecords.length === 0 ? (
                <div className="text-center py-6 bg-accent/50 border border-border border-dashed rounded-xl">
                  <p className="text-subtle text-sm">No historical records yet.</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {pastRecords.map(record => (
                    <div key={record.id} className="border border-border rounded-xl p-4 space-y-3">
                      {/* Record header */}
                      <div className="flex justify-between items-center bg-accent/40 rounded-lg p-2.5">
                        <div>
                          <span className="font-semibold text-foreground text-sm">
                            Day {record.current_day_number} &middot;{' '}
                            {new Date(record.record_date + 'T00:00:00').toLocaleDateString('en-US', {
                              weekday: 'short', month: 'short', day: 'numeric',
                            })}
                          </span>
                          {record.trainer_id && (
                            <span className="text-xs text-muted-foreground ml-2">
                              · Trainer ID on file
                            </span>
                          )}
                        </div>
                        <span className="text-xs px-2 py-0.5 rounded-md bg-foreground/10 text-muted-foreground font-medium">
                          Locked
                        </span>
                      </div>

                      {/* Tasks */}
                      <div className="text-sm space-y-2 px-1">
                        {record.tasks?.map((task: any) => (
                          <div key={task.id} className="flex gap-2.5 items-start">
                            {task.is_completed
                              ? <span className="text-success text-base shrink-0">&check;</span>
                              : <span className="text-danger shrink-0 font-bold">&times;</span>}
                            <span className={task.is_completed ? 'text-subtle line-through' : 'text-foreground font-medium'}>
                              {task.topic_title}
                            </span>
                          </div>
                        ))}
                      </div>

                      {/* Trainee review */}
                      {record.trainer_rating != null && (
                        <div className="bg-accent/20 p-3 rounded-lg border border-border/50 text-xs space-y-1">
                          <div className="flex items-center gap-2">
                            <Star className="w-3.5 h-3.5 text-warning" />
                            <span className="font-bold uppercase tracking-wider text-muted-foreground">Trainee Review</span>
                          </div>
                          <div className="text-sm text-warning font-black">
                            {'★'.repeat(record.trainer_rating)}{'☆'.repeat(5 - record.trainer_rating)}
                          </div>
                          {record.trainee_comments && (
                            <p className="text-foreground">{record.trainee_comments}</p>
                          )}
                        </div>
                      )}

                      {/* Manager comments */}
                      {record.manager_comments && (
                        <div className="bg-info/5 p-3 rounded-lg border border-info/20 text-xs space-y-1">
                          <span className="font-bold uppercase tracking-wider text-info">Manager Note</span>
                          <p className="text-foreground whitespace-pre-line">{record.manager_comments}</p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Right: manager actions */}
          <div className="space-y-6">
            <ManagerComments record={todayRecord} traineeId={traineeId} />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function TraineeManagement() {
  const [tab, setTab] = useState<Tab>('today');
  const [allTrainees, setAllTrainees] = useState<any[]>([]);
  const [activeRecords, setActiveRecords] = useState<ActiveRecord[]>([]);
  const [escalated, setEscalated] = useState<EscalatedRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Drilldown state — null means showing the tab overview
  const [selectedTrainee, setSelectedTrainee] = useState<{ id: string; name: string } | null>(null);

  const load = async () => {
    setIsLoading(true);
    try {
      const [empRes, activeRes, escalatedRes] = await Promise.all([
        axiosClient.get('/employees/'),
        axiosClient.get('/training/daily/active'),
        axiosClient.get('/training/escalated'),
      ]);
      setAllTrainees(empRes.data.filter((e: any) => e.role?.toLowerCase() === 'trainee'));
      setActiveRecords(activeRes.data);
      setEscalated(escalatedRes.data);
    } catch (err) {
      console.error('Failed to load trainee hub:', err);
    }
    setIsLoading(false);
  };

  useEffect(() => { load(); }, []);

  const openTrainee = (id: string, name: string) => {
    setSelectedTrainee({ id, name });
  };

  const closeTrainee = () => setSelectedTrainee(null);

  const tabs: { key: Tab; label: string; icon: React.ElementType; count?: number }[] = [
    { key: 'today',     label: "Today's Pairings", icon: ClipboardList, count: activeRecords.length },
    { key: 'escalated', label: 'Escalated',         icon: AlertTriangle, count: escalated.length },
    { key: 'history',   label: 'Trainee History',   icon: Calendar },
  ];

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 opacity-50">
        <Loader2 className="w-8 h-8 text-primary animate-spin mb-4" />
        <p className="text-sm font-medium">Loading Trainee Hub...</p>
      </div>
    );
  }

  // Drilldown view — overlays the tab content
  if (selectedTrainee) {
    return (
      <div className="space-y-6 animate-slide-up">
        <div className="flex items-center justify-between">
          <h1 className="page-title">Trainee Hub</h1>
          <button onClick={load} className="btn-ghost text-muted-foreground flex items-center gap-2 text-sm">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
        <HistoryView
          traineeId={selectedTrainee.id}
          traineeName={selectedTrainee.name}
          allTrainees={allTrainees}
          onClose={closeTrainee}
          onSelectTrainee={openTrainee}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Page header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="page-title">Trainee Hub</h1>
          <p className="text-subtle mt-1">Monitor active pairings, escalations, and trainee history.</p>
        </div>
        <button onClick={load} className="btn-ghost text-muted-foreground flex items-center gap-2 text-sm">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 w-fit">
        {tabs.map(({ key, label, icon: Icon, count }) => (
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
            {count != null && count > 0 && (
              <span className={`text-xs font-bold px-1.5 py-0.5 rounded-full ${
                key === 'escalated'
                  ? 'bg-warning/20 text-warning'
                  : 'bg-primary/15 text-primary'
              }`}>
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'today' && (
        <TodayTab activeRecords={activeRecords} onSelectTrainee={openTrainee} />
      )}

      {tab === 'escalated' && (
        <EscalatedTab escalated={escalated} onSelectTrainee={openTrainee} />
      )}

      {tab === 'history' && (
        <div className="space-y-4">
          {allTrainees.length === 0 ? (
            <p className="text-subtle text-sm">No active trainees in the system.</p>
          ) : (
            <>
              <p className="text-sm text-subtle">Select a trainee to view their full training history.</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {allTrainees.map(t => {
                  const active = activeRecords.find(r => r.trainee?.id === t.id);
                  const isEscalated = escalated.some(e => e.trainee?.id === t.id);
                  return (
                    <button
                      key={t.id}
                      onClick={() => openTrainee(t.id, t.name ?? t.first_name ?? 'Unknown')}
                      className="card-elevated border hover:border-primary/50 transition-colors text-left w-full group"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <p className="font-semibold text-foreground text-sm group-hover:text-primary transition-colors">
                            {t.name ?? t.first_name}
                          </p>
                          {active ? (
                            <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1">
                              <UserCheck className="w-3 h-3" />
                              {active.trainer?.name ?? 'No trainer'} · Day {active.record.current_day_number}
                            </p>
                          ) : (
                            <p className="text-xs text-subtle mt-0.5 italic">Not dispatched today</p>
                          )}
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          {isEscalated && (
                            <AlertTriangle className="w-3.5 h-3.5 text-warning" title="Has escalated tasks" />
                          )}
                          <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors" />
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
