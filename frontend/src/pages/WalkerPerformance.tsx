import React, { useState, useEffect, useMemo, useCallback } from 'react';
import axiosClient from '../api/axiosClient';
import {
  Star, Users, TrendingUp, TrendingDown, Minus, ChevronRight, X,
  AlertTriangle, BarChart2, ArrowUpDown, Download, Calendar, AlertCircle,
  Info, ChevronLeft,
} from 'lucide-react';
import ErrorBanner from '../components/ui/ErrorBanner';
import { getLocalYMD } from '../utils/date';
import type {
  WalkerSummary, WalkerProfile, WalkerConsistency,
} from '../api/types';

// ---------------------------------------------------------------------------
// Grade helpers
// ---------------------------------------------------------------------------

const GRADE_CONFIG: Record<string, { bg: string; text: string; border: string; label: string }> = {
  A: { bg: 'bg-success/15', text: 'text-success', border: 'border-success/30', label: 'Excellent' },
  B: { bg: 'bg-info/15',    text: 'text-info',    border: 'border-info/30',    label: 'Good'      },
  C: { bg: 'bg-warning/15', text: 'text-warning', border: 'border-warning/30', label: 'Average'   },
  D: { bg: 'bg-orange-500/15', text: 'text-orange-500', border: 'border-orange-500/30', label: 'Below Average' },
  F: { bg: 'bg-danger/15',  text: 'text-danger',  border: 'border-danger/30',  label: 'Poor'      },
};

function GradeBadge({ grade, large }: { grade: string | null; large?: boolean }) {
  if (!grade) return <span className="text-xs text-subtle italic">Ungraded</span>;
  const cfg = GRADE_CONFIG[grade] ?? GRADE_CONFIG['F'];
  return (
    <span className={`inline-flex items-center justify-center font-black border rounded-xl ${cfg.bg} ${cfg.text} ${cfg.border} ${large ? 'text-3xl w-12 h-12' : 'text-sm w-8 h-8'}`}>
      {grade}
    </span>
  );
}

function StarBar({ value, max = 5 }: { value: number | null; max?: number }) {
  if (value === null) return <span className="text-xs text-subtle">N/A</span>;
  return (
    <span className="flex items-center gap-0.5">
      {Array.from({ length: max }).map((_, i) => (
        <Star
          key={i}
          className={`w-3.5 h-3.5 ${i < Math.round(value) ? 'fill-yellow-400 text-yellow-400' : 'text-border'}`}
        />
      ))}
      <span className="text-xs font-semibold text-foreground ml-1">{value.toFixed(1)}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// CSV export
// ---------------------------------------------------------------------------

function exportToCSV(walkers: WalkerSummary[], minShifts: number) {
  const headers = ['Name', 'Role', 'Grade', 'Grade Eligible', 'Avg Peer Stars', 'Ratings Received', 'Distinct Raters'];
  const rows = walkers.map(w => [
    w.employee_name,
    w.role,
    w.grade ?? (w.grade_eligible ? 'F' : `< ${minShifts} ratings`),
    w.grade_eligible ? 'Yes' : 'No',
    w.avg_stars !== null ? w.avg_stars.toFixed(2) : '',
    w.ratings_received,
    w.distinct_raters,
  ]);

  const csv = [headers, ...rows]
    .map(row => row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(','))
    .join('\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `walker-performance-${getLocalYMD()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Driver Consistency Section
// ---------------------------------------------------------------------------

function DriverConsistencySection({ walkerId }: { walkerId: string }) {
  const [data, setData] = useState<WalkerConsistency | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    axiosClient.get(`/field-ops/walker-consistency/${walkerId}`)
      .then(r => setData(r.data))
      .catch(() => setError('Failed to load driver consistency data.'))
      .finally(() => setLoading(false));
  }, [walkerId]);

  if (loading) return (
    <div className="px-6 py-4 border-t border-border flex items-center justify-center">
      <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );

  if (error) return (
    <div className="px-6 py-4 border-t border-border">
      <ErrorBanner message={error} />
    </div>
  );

  if (!data || data.drivers.length < 2) return null;

  const flagged = data.drivers.filter(d => d.flagged);

  return (
    <div className="px-6 py-4 border-t border-border">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-sm font-semibold text-foreground">Driver Consistency</h3>
        {flagged.length > 0 && (
          <span className="inline-flex items-center gap-1 text-xs font-bold text-warning bg-warning/10 border border-warning/20 rounded-full px-2 py-0.5">
            <AlertCircle className="w-3 h-3" />
            {flagged.length} driver{flagged.length !== 1 ? 's' : ''} flagged
          </span>
        )}
        <span className="ml-auto text-xs text-subtle">walker avg: {data.walker_avg_stars?.toFixed(1)} ★</span>
      </div>

      {flagged.length > 0 && (
        <div className="mb-3 p-2.5 rounded-lg bg-warning/5 border border-warning/20 text-xs text-subtle leading-relaxed">
          <Info className="w-3.5 h-3.5 inline mr-1 text-warning" />
          Flagged drivers deviate ≥{data.flag_threshold} star from this walker's overall average.
          This may indicate driver rating bias rather than actual performance variation.
        </div>
      )}

      <div className="space-y-2">
        {data.drivers.map(d => {
          const barWidth = Math.min(100, ((d.avg_stars ?? 0) / 5) * 100);
          const deviationColor = (d.deviation ?? 0) > 0 ? 'text-success' : 'text-danger';
          return (
            <div key={d.driver_id} className={`rounded-lg border p-2.5 ${d.flagged ? 'border-warning/40 bg-warning/5' : 'border-border bg-background'}`}>
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">{d.driver_name}</span>
                  {d.flagged && <AlertCircle className="w-3.5 h-3.5 text-warning" />}
                  <span className="text-xs text-subtle">{d.shift_count} shift{d.shift_count !== 1 ? 's' : ''}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-foreground">{d.avg_stars?.toFixed(1) ?? '—'} ★</span>
                  <span className={`text-xs font-semibold ${deviationColor}`}>
                    {(d.deviation ?? 0) > 0 ? '+' : ''}{d.deviation?.toFixed(1) ?? '—'}
                  </span>
                </div>
              </div>
              <div className="h-1.5 rounded-full bg-border overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${d.flagged ? 'bg-warning' : 'bg-primary'}`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Walker Profile Panel (slide-in)
// ---------------------------------------------------------------------------

function WalkerProfilePanel({ walkerId, onClose }: { walkerId: string; onClose: () => void }) {
  const [profile, setProfile] = useState<WalkerProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const fetchProfile = useCallback(() => {
    setLoading(true);
    setProfileError(null);
    const params = new URLSearchParams();
    if (startDate) params.set('start_date', startDate);
    if (endDate) params.set('end_date', endDate);
    const qs = params.toString() ? `?${params.toString()}` : '';
    axiosClient.get(`/field-ops/walker-profile/${walkerId}${qs}`)
      .then(r => setProfile(r.data))
      .catch(() => setProfileError('Failed to load walker profile.'))
      .finally(() => setLoading(false));
  }, [walkerId, startDate, endDate]);

  useEffect(() => {
    setProfile(null);
    setStartDate('');
    setEndDate('');
  }, [walkerId]);

  useEffect(() => {
    fetchProfile();
  }, [fetchProfile]);

  // Recent trend: compare recent half vs older half of rated history
  const trend = useMemo(() => {
    if (!profile) return null;
    const rated = profile.ratings;
    if (rated.length < 4) return null;
    const recent = rated.slice(0, Math.ceil(rated.length / 2));
    const older  = rated.slice(Math.ceil(rated.length / 2));
    const recentAvg = recent.reduce((s, r) => s + r.stars, 0) / recent.length;
    const olderAvg  = older.reduce((s, r)  => s + r.stars, 0) / older.length;
    const diff = recentAvg - olderAvg;
    if (Math.abs(diff) < 0.2) return 'stable';
    return diff > 0 ? 'up' : 'down';
  }, [profile]);

  const isFiltered = !!(startDate || endDate);
  const cfg = profile?.grade ? GRADE_CONFIG[profile.grade] : null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={onClose} />

      {/* Panel */}
      <div className="relative w-full max-w-lg bg-card border-l border-border shadow-2xl flex flex-col animate-slide-up overflow-hidden">
        {/* Header */}
        <div className={`px-6 py-5 border-b border-border flex items-start justify-between gap-4 ${cfg ? cfg.bg : ''}`}>
          <div className="flex items-center gap-4">
            <GradeBadge grade={profile?.grade ?? null} large />
            <div>
              <h2 className="text-lg font-bold text-foreground">{profile?.walker_name ?? '…'}</h2>
              {profile?.grade && cfg && (
                <p className={`text-sm font-semibold ${cfg.text}`}>{cfg.label} — Grade {profile.grade}</p>
              )}
              {trend === 'up'     && <p className="text-xs text-success flex items-center gap-1 mt-0.5"><TrendingUp className="w-3.5 h-3.5" /> Improving</p>}
              {trend === 'down'   && <p className="text-xs text-danger flex items-center gap-1 mt-0.5"><TrendingDown className="w-3.5 h-3.5" /> Declining</p>}
              {trend === 'stable' && <p className="text-xs text-subtle flex items-center gap-1 mt-0.5"><Minus className="w-3.5 h-3.5" /> Stable</p>}
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost text-muted-foreground hover:text-foreground p-1.5 shrink-0">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Date range filter */}
        <div className="px-6 py-3 border-b border-border bg-accent/20 flex items-center gap-2 flex-wrap">
          <Calendar className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs text-muted-foreground">Filter history:</span>
          <input
            type="date"
            value={startDate}
            onChange={e => setStartDate(e.target.value)}
            className="text-xs px-2 py-1 rounded-lg border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
          <span className="text-xs text-subtle">–</span>
          <input
            type="date"
            value={endDate}
            onChange={e => setEndDate(e.target.value)}
            className="text-xs px-2 py-1 rounded-lg border border-border bg-background focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
          {isFiltered && (
            <button
              onClick={() => { setStartDate(''); setEndDate(''); }}
              className="text-xs text-primary hover:underline ml-auto"
            >
              Clear
            </button>
          )}
        </div>

        {loading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="w-7 h-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : profileError ? (
          <div className="flex-1 flex items-center justify-center p-6">
            <ErrorBanner message={profileError} />
          </div>
        ) : profile ? (
          <div className="flex-1 overflow-y-auto">
            {/* KPI strip — always all-time */}
            <div className="grid grid-cols-2 divide-x divide-border border-b border-border">
              {[
                { label: 'Ratings Received', value: profile.ratings_received },
                { label: 'Distinct Raters',  value: profile.distinct_raters },
              ].map(k => (
                <div key={k.label} className="px-3 py-4 text-center">
                  <p className="text-xs text-muted-foreground">{k.label}</p>
                  <p className="text-lg font-bold mt-0.5 text-foreground">{k.value}</p>
                </div>
              ))}
            </div>

            {/* Avg stars */}
            <div className="px-6 py-4 border-b border-border flex items-center justify-between">
              <span className="text-sm font-medium text-muted-foreground">All-time Average Rating</span>
              <StarBar value={profile.avg_stars} />
            </div>

            {/* Rating history */}
            <div className="px-6 py-4">
              <div className="flex items-center gap-2 mb-3">
                <h3 className="text-sm font-semibold text-foreground">Rating History</h3>
                <span className="text-xs font-normal text-subtle">
                  ({profile.ratings.length} {isFiltered ? 'in range' : 'total'})
                </span>
                {isFiltered && (
                  <span className="text-xs italic text-primary ml-1">filtered</span>
                )}
              </div>

              {profile.ratings.length === 0 ? (
                <p className="text-sm text-subtle text-center py-6">
                  {isFiltered ? 'No ratings in this date range.' : 'No ratings recorded yet.'}
                </p>
              ) : (
                <div className="space-y-2">
                  {profile.ratings.map(r => (
                    <div
                      key={r.id}
                      className="rounded-xl border p-3 border-border bg-background"
                    >
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-xs font-semibold text-foreground">{r.date}</span>
                        <span className="text-xs text-subtle">by {r.rater_name}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <StarBar value={r.stars} />
                        {r.comment && (
                          <span className="text-xs text-subtle italic truncate flex-1">"{r.comment}"</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Driver consistency */}
            <DriverConsistencySection walkerId={walkerId} />
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-subtle text-sm">
            No profile data available.
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type SortKey = 'grade' | 'stars' | 'ratings' | 'raters' | 'name';

const GRADE_ORDER: Record<string, number> = { A: 0, B: 1, C: 2, D: 3, F: 4 };

const MIN_SHIFT_OPTIONS = [
  { value: 1, label: 'All crew' },
  { value: 3, label: '≥ 3 ratings' },
  { value: 5, label: '≥ 5 ratings' },
  { value: 10, label: '≥ 10 ratings' },
];

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

export default function WalkerPerformance() {
  const [walkers, setWalkers]   = useState<WalkerSummary[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [search, setSearch]     = useState('');
  const [filterGrade, setFilterGrade] = useState('');
  const [sortKey, setSortKey]   = useState<SortKey>('grade');
  const [sortAsc, setSortAsc]   = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [minShifts, setMinShifts] = useState(5);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const fetchLeaderboard = useCallback((threshold: number) => {
    setLoading(true);
    setError(null);
    axiosClient.get(`/field-ops/walker-leaderboard?min_ratings=${threshold}&limit=200&offset=0`)
      .then(r => setWalkers(r.data.items ?? r.data))
      .catch(() => setError('Failed to load the team leaderboard. Please refresh.'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetchLeaderboard(minShifts);
  }, [fetchLeaderboard, minShifts]);

  const toggleSort = (key: SortKey) => {
    setPage(1);
    if (sortKey === key) setSortAsc(a => !a);
    else { setSortKey(key); setSortAsc(true); }
  };

  // Reset to page 1 whenever filters or search change
  useEffect(() => { setPage(1); }, [search, filterGrade, minShifts]);

  const visible = useMemo(() => {
    let list = walkers.filter(w => {
      if (search && !w.employee_name.toLowerCase().includes(search.toLowerCase())) return false;
      if (filterGrade === '__ungraded') return !w.grade;
      if (filterGrade && w.grade !== filterGrade) return false;
      return true;
    });
    list.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'grade':    cmp = (GRADE_ORDER[a.grade ?? 'Z'] ?? 5) - (GRADE_ORDER[b.grade ?? 'Z'] ?? 5); break;
        case 'stars':    cmp = (a.avg_stars ?? -1) - (b.avg_stars ?? -1); break;
        case 'ratings':  cmp = a.ratings_received - b.ratings_received; break;
        case 'raters':   cmp = a.distinct_raters - b.distinct_raters; break;
        case 'name':     cmp = a.employee_name.localeCompare(b.employee_name); break;
      }
      return sortAsc ? cmp : -cmp;
    });
    return list;
  }, [walkers, search, filterGrade, sortKey, sortAsc]);

  const totalPages = Math.max(1, Math.ceil(visible.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageSlice = visible.slice((safePage - 1) * pageSize, safePage * pageSize);

  // Fleet-level KPIs — based on grade-eligible walkers only
  const graded = useMemo(() => walkers.filter(w => w.grade !== null), [walkers]);
  const ungraded = useMemo(() => walkers.filter(w => w.grade === null && w.ratings_received > 0), [walkers]);

  const gradeDistribution = useMemo(() => {
    const dist: Record<string, number> = { A: 0, B: 0, C: 0, D: 0, F: 0 };
    graded.forEach(w => { if (w.grade) dist[w.grade]++; });
    return dist;
  }, [graded]);

  /* At-Risk on TWO independent signals (ADR-268), not peer grade alone.
     Peer grade is a popularity-adjacent measure; on its own it made this list
     a reputation surface. rts_rate_vs_class is an outcome the person controls,
     normalised for route difficulty — raw rate runs 2.10% on easy routes
     against 10.81% on heavy, so ranking on it would flag whoever drew the hard
     work.

     Either signal qualifies, and each row says WHICH — "D grade" and "returns
     1.7x the norm for comparable routes" call for different conversations, and
     a merged score would hide that. */
  const atRisk = useMemo(
    () => walkers
      .filter(w => w.grade === 'D' || w.grade === 'F' || w.outcome_at_risk)
      .map(w => ({
        ...w,
        reasons: [
          ...(w.grade === 'D' || w.grade === 'F' ? [`${w.grade} peer grade`] : []),
          ...(w.outcome_at_risk && w.rts_rate_vs_class
            ? [`${w.rts_rate_vs_class.toFixed(1)}x returns for this difficulty`]
            : []),
        ],
      })),
    [walkers],
  );

  const fleetAvgStars = useMemo(() => {
    const rated = walkers.filter(w => w.avg_stars !== null);
    if (rated.length === 0) return null;
    return (rated.reduce((s, w) => s + (w.avg_stars ?? 0), 0) / rated.length).toFixed(2);
  }, [walkers]);

  const SortBtn = ({ col, label }: { col: SortKey; label: string }) => (
    <button
      onClick={() => toggleSort(col)}
      className={`flex items-center gap-1 text-xs uppercase tracking-wider font-semibold transition-colors ${sortKey === col ? 'text-primary' : 'text-muted-foreground hover:text-foreground'}`}
    >
      {label}
      <ArrowUpDown className={`w-3 h-3 ${sortKey === col ? 'opacity-100' : 'opacity-40'}`} />
    </button>
  );

  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-slide-up">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-9 h-9 rounded-xl gradient-primary shadow-sm shadow-primary/30">
          <Users className="w-4 h-4 text-primary-foreground" />
        </div>
        <div>
          <h1 className="page-title">Walker Performance</h1>
          <p className="text-subtle mt-0.5">All-time grades, attendance, and rating history for every walker.</p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {/* Min shift threshold */}
          <select
            value={minShifts}
            onChange={e => setMinShifts(Number(e.target.value))}
            className="px-3 py-1.5 rounded-lg border border-border bg-background text-sm focus:outline-none"
            title="Minimum shifts required to earn a grade"
          >
            {MIN_SHIFT_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {/* CSV export */}
          {!loading && walkers.length > 0 && (
            <button
              onClick={() => exportToCSV(visible, minShifts)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border bg-background text-sm text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
              title="Export visible walkers to CSV"
            >
              <Download className="w-4 h-4" />
              Export CSV
            </button>
          )}
        </div>
      </div>

      <ErrorBanner message={error} />

      {loading ? (
        <div className="flex h-60 items-center justify-center">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <>
          {/* Fleet KPI row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="card-elevated">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Total Walkers</p>
              <p className="text-2xl font-bold mt-1 text-foreground">{walkers.length}</p>
              <p className="text-xs text-subtle mt-0.5">{graded.length} graded · {ungraded.length} ungraded</p>
            </div>
            <div className="card-elevated">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Fleet Avg Rating</p>
              <p className="text-2xl font-bold mt-1 text-foreground">{fleetAvgStars ?? '—'} ★</p>
              <p className="text-xs text-subtle mt-0.5">across all rated shifts</p>
            </div>
            <div className="card-elevated">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Peer Ratings</p>
              <p className="text-2xl font-bold mt-1 text-foreground">
                {walkers.reduce((s, w) => s + w.ratings_received, 0)}
              </p>
              <p className="text-xs text-subtle mt-0.5">total submitted this window</p>
            </div>
            <div className="card-elevated">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">At Risk</p>
              <p className={`text-2xl font-bold mt-1 ${atRisk.length > 0 ? 'text-danger' : 'text-subtle'}`}>{atRisk.length}</p>
              <p className="text-xs text-subtle mt-0.5">grade or return rate</p>
            </div>
          </div>

          {/* Ungraded notice */}
          {ungraded.length > 0 && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-accent/40 border border-border text-xs text-subtle">
              <Info className="w-4 h-4 text-muted-foreground mt-0.5 shrink-0" />
              <span>
                <span className="font-semibold text-foreground">{ungraded.length} walker{ungraded.length !== 1 ? 's' : ''}</span>
                {' '}below the {minShifts}-shift threshold and shown as ungraded. Adjust the threshold above to include them.
              </span>
            </div>
          )}

          {/* Grade distribution bar */}
          {graded.length > 0 && (
            <div className="card">
              <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
                <BarChart2 className="w-5 h-5 text-primary" />
                <h2 className="text-base font-semibold text-foreground">Grade Distribution</h2>
                <span className="ml-auto text-xs text-subtle">{graded.length} graded walkers</span>
              </div>
              <div className="flex items-end gap-3 h-20">
                {(['A', 'B', 'C', 'D', 'F'] as const).map(g => {
                  const count = gradeDistribution[g];
                  const pct   = graded.length > 0 ? (count / graded.length) : 0;
                  const cfg   = GRADE_CONFIG[g];
                  return (
                    <div key={g} className="flex-1 flex flex-col items-center gap-1">
                      <span className={`text-xs font-bold ${cfg.text}`}>{count}</span>
                      <div
                        className={`w-full rounded-t-lg ${cfg.bg} border-t-2 ${cfg.border} transition-all`}
                        style={{ height: `${Math.max(pct * 64, count > 0 ? 8 : 2)}px` }}
                      />
                      <span className={`text-xs font-black ${cfg.text}`}>{g}</span>
                    </div>
                  );
                })}
              </div>
              <div className="flex flex-wrap gap-3 mt-3">
                {(['A', 'B', 'C', 'D', 'F'] as const).map(g => (
                  <span key={g} className={`text-xs ${GRADE_CONFIG[g].text}`}>
                    {g} = {GRADE_CONFIG[g].label}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* At-risk callout */}
          {atRisk.length > 0 && (
            <div className="card border-danger/30 bg-danger/5">
              <div className="flex items-center gap-2 mb-3">
                <AlertTriangle className="w-4 h-4 text-danger" />
                <h2 className="text-sm font-semibold text-danger">At-Risk ({atRisk.length})</h2>
                <span className="text-xs text-subtle ml-1">peer grade or return rate · consider a review</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {atRisk.map(w => (
                  <button
                    key={w.employee_id}
                    onClick={() => setSelectedId(w.employee_id)}
                    className="flex items-start gap-2 px-3 py-1.5 rounded-lg bg-background border border-danger/30 hover:bg-danger/10 transition-colors text-left"
                    title={w.reasons.join(' · ')}
                  >
                    <GradeBadge grade={w.grade} />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium text-foreground">{w.employee_name}</span>
                      {/* Why they are here. A flag with no reason is an
                          accusation; a flag with a reason is a starting point. */}
                      <span className="block text-[10px] text-subtle">{w.reasons.join(' · ')}</span>
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Leaderboard */}
          <div className="card">
            <div className="flex items-center gap-2 border-b border-border pb-3 mb-4 flex-wrap gap-y-2">
              <h2 className="text-base font-semibold text-foreground">Team Leaderboard</h2>

              <div className="ml-auto flex items-center gap-2 flex-wrap">
                {/* Search */}
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="Search name…"
                  className="w-36 px-3 py-1.5 rounded-lg border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
                {/* Grade filter */}
                <select
                  value={filterGrade}
                  onChange={e => setFilterGrade(e.target.value)}
                  className="px-3 py-1.5 rounded-lg border border-border bg-background text-sm focus:outline-none"
                >
                  <option value="">All grades</option>
                  {['A', 'B', 'C', 'D', 'F'].map(g => (
                    <option key={g} value={g}>{g} — {GRADE_CONFIG[g].label}</option>
                  ))}
                  {ungraded.length > 0 && (
                    <option value="__ungraded">Ungraded</option>
                  )}
                </select>
                {/* Page size */}
                <select
                  value={pageSize}
                  onChange={e => { setPageSize(Number(e.target.value)); setPage(1); }}
                  className="px-3 py-1.5 rounded-lg border border-border bg-background text-sm focus:outline-none"
                  title="Rows per page"
                >
                  {PAGE_SIZE_OPTIONS.map(n => (
                    <option key={n} value={n}>{n} / page</option>
                  ))}
                </select>
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="pb-2 pr-4 text-left w-8">#</th>
                    <th className="pb-2 pr-6 text-left"><SortBtn col="name"    label="Name"     /></th>
                    <th className="pb-2 pr-4 text-center"><SortBtn col="grade"   label="Grade"    /></th>
                    <th className="pb-2 pr-4 text-center"><SortBtn col="stars"   label="Avg ★"    /></th>
                    <th className="pb-2 pr-4 text-center"><SortBtn col="ratings" label="Ratings"  /></th>
                    <th className="pb-2 pr-4 text-center"><SortBtn col="raters"  label="Raters"   /></th>
                    <th className="pb-2 text-right text-xs text-muted-foreground uppercase tracking-wider">Detail</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {visible.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-10 text-center text-subtle text-sm">No crew match the selected filters.</td>
                    </tr>
                  ) : (
                    pageSlice.map((w, i) => (
                      <tr
                        key={w.employee_id}
                        className="hover:bg-accent/20 transition-colors cursor-pointer"
                        onClick={() => setSelectedId(w.employee_id)}
                      >
                        <td className="py-3 pr-4 text-xs text-subtle">{(safePage - 1) * pageSize + i + 1}</td>
                        <td className="py-3 pr-6">
                          <span className="font-semibold text-foreground">{w.employee_name}</span>
                          <span className="ml-2 text-xs text-subtle capitalize">{w.role}</span>
                          {!w.grade_eligible && (
                            <span className="ml-2 text-xs text-subtle italic">({w.ratings_received} rating{w.ratings_received !== 1 ? 's' : ''})</span>
                          )}
                        </td>
                        <td className="py-3 pr-4 text-center">
                          <GradeBadge grade={w.grade} />
                        </td>
                        <td className="py-3 pr-4 text-center">
                          {w.avg_stars !== null ? (
                            <span className="flex items-center justify-center gap-1 text-sm font-bold text-foreground">
                              {w.avg_stars.toFixed(1)}
                              <Star className="w-3.5 h-3.5 fill-yellow-400 text-yellow-400" />
                            </span>
                          ) : (
                            <span className="text-xs text-subtle">—</span>
                          )}
                        </td>
                        <td className="py-3 pr-4 text-center text-sm text-foreground">{w.ratings_received || '—'}</td>
                        <td className="py-3 pr-4 text-center text-sm text-foreground">{w.distinct_raters || '—'}</td>
                        <td className="py-3 text-right">
                          <ChevronRight className="w-4 h-4 text-muted-foreground inline-block" />
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination controls */}
            {totalPages > 1 && (
              <div className="mt-4 pt-4 border-t border-border/50 flex items-center justify-between gap-2 flex-wrap">
                <span className="text-xs text-subtle">
                  Showing {(safePage - 1) * pageSize + 1}–{Math.min(safePage * pageSize, visible.length)} of {visible.length}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage(1)}
                    disabled={safePage === 1}
                    className="px-2 py-1 rounded-lg text-xs text-muted-foreground hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    «
                  </button>
                  <button
                    onClick={() => setPage(p => Math.max(1, p - 1))}
                    disabled={safePage === 1}
                    className="px-2 py-1 rounded-lg text-xs text-muted-foreground hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                  </button>

                  {/* Page number pills */}
                  {Array.from({ length: totalPages }, (_, i) => i + 1)
                    .filter(n => n === 1 || n === totalPages || Math.abs(n - safePage) <= 2)
                    .reduce<(number | '…')[]>((acc, n, idx, arr) => {
                      if (idx > 0 && n - (arr[idx - 1] as number) > 1) acc.push('…');
                      acc.push(n);
                      return acc;
                    }, [])
                    .map((n, idx) =>
                      n === '…' ? (
                        <span key={`ellipsis-${idx}`} className="px-1 text-xs text-subtle">…</span>
                      ) : (
                        <button
                          key={n}
                          onClick={() => setPage(n as number)}
                          className={`min-w-[28px] px-2 py-1 rounded-lg text-xs font-medium transition-colors ${
                            safePage === n
                              ? 'gradient-primary text-primary-foreground shadow-sm'
                              : 'text-muted-foreground hover:bg-accent'
                          }`}
                        >
                          {n}
                        </button>
                      )
                    )}

                  <button
                    onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                    disabled={safePage === totalPages}
                    className="px-2 py-1 rounded-lg text-xs text-muted-foreground hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => setPage(totalPages)}
                    disabled={safePage === totalPages}
                    className="px-2 py-1 rounded-lg text-xs text-muted-foreground hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  >
                    »
                  </button>
                </div>
              </div>
            )}

            {/* Grade legend */}
            <div className="mt-4 pt-4 border-t border-border/50 text-xs text-subtle space-y-1">
              <p className="font-semibold text-muted-foreground">How grades are calculated</p>
              <p>Grade = weighted score of presence rate (50%) + average star rating (50%). A ≥ 90%, B ≥ 75%, C ≥ 60%, D ≥ 45%, F &lt; 45%. Walkers below the minimum shift threshold are shown as ungraded to avoid statistically noisy grades.</p>
            </div>
          </div>
        </>
      )}

      {/* Drill-down panel */}
      {selectedId && (
        <WalkerProfilePanel
          walkerId={selectedId}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}
