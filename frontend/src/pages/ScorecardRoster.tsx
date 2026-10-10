/**
 * Individual scorecard roster — Tier 3, management and admin only.
 *
 * Named deliberately, matching /field-ops/walker-leaderboard which already shows
 * named performance to this same audience. Anonymising it would make it
 * unactionable for the only people authorised to act on it.
 *
 * Sorted worst-first (flagged metric count, then declining standing): the point
 * of a roster is finding who needs attention, not alphabetical browsing.
 *
 * See docs/SCORECARD_ACCESS_MODEL.md — dispatch is excluded from this tier.
 */
import React, { useCallback, useEffect, useState } from 'react';
import SelectMenu from '../components/ui/SelectMenu';
import {
  Users, RefreshCw, AlertTriangle, TrendingUp, TrendingDown, Minus, X, Lock, Loader2,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import ErrorBanner from '../components/ui/ErrorBanner';
import type {
  IndividualRosterResponse, IndividualRosterRow, IndividualTrendResponse,
  RetentionHoldIn, ScorecardRetentionRow,
} from '../api/types';
import { count, pct } from '../utils/metric';
import { formatDate, getLocalYMD } from '../utils/date';
import { errorText } from '../utils/errorText';

function standingTone(s?: string | null): string {
  if (!s) return 'text-muted-foreground';
  const u = s.toUpperCase();
  if (u.includes('FANTASTIC') || u.includes('PLATINUM')) return 'text-success';
  if (u.includes('GREAT') || u.includes('GOLD')) return 'text-info';
  if (u.includes('FAIR') || u.includes('SILVER')) return 'text-warning';
  return 'text-danger';
}

/** Standing movement. Not metric direction — this is ladder position, where
 *  "improved" means a better tier, so it needs its own renderer. */
function Movement({ dir }: { dir?: string | null }) {
  const c = 'w-3.5 h-3.5 shrink-0';
  if (dir === 'improved') return <TrendingUp className={`${c} text-success`} />;
  if (dir === 'declined') return <TrendingDown className={`${c} text-danger`} />;
  if (dir === 'unchanged') return <Minus className={`${c} text-muted-foreground`} />;
  return <Minus className={`${c} text-muted-foreground/40`} />;
}

export default function ScorecardRoster() {
  const [data, setData] = useState<IndividualRosterResponse | null>(null);
  const [weeks, setWeeks] = useState(4);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<IndividualTrendResponse | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<IndividualRosterResponse>(
        `/scorecards/individual/roster?weeks=${weeks}`,
      );
      setData(res.data);
    } catch {
      setError('Failed to load the scorecard roster.');
    } finally {
      setLoading(false);
    }
  }, [weeks]);

  useEffect(() => { load(); }, [load]);

  const openDetail = async (row: IndividualRosterRow) => {
    try {
      const res = await axiosClient.get<IndividualTrendResponse>(
        `/scorecards/individual/${row.employee_id}/trend?weeks=12`,
      );
      setDetail(res.data);
    } catch {
      setError(`Could not load ${row.employee_name}'s trend.`);
    }
  };

  return (
    <div className="space-y-8 animate-slide-up">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Users className="w-5 h-5 text-primary" /> Scorecard Roster
          </h1>
          <p className="text-subtle mt-1">
            Individual Amazon standings, worst first.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-36">
            <SelectMenu
              value={String(weeks)}
              options={[
                { value: '2',  label: '2 weeks' },
                { value: '4',  label: '4 weeks' },
                { value: '12', label: '12 weeks' },
              ]}
              placeholder="Weeks considered"
              ariaLabel="Weeks considered"
              onChange={v => setWeeks(Number(v))}
            />
          </div>
          <button onClick={load} className="btn-ghost flex items-center gap-2 text-sm">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>
      </div>

      <ErrorBanner message={error} />

      {/* Coverage. A thin roster should read as missing data, not a small team —
          without this the page silently understates the crew. */}
      {data && (data.employees_without_scorecards ?? 0) > 0 && (
        <div className="flex items-start gap-2 px-4 py-2.5 rounded-lg bg-warning/10 border border-warning/30 text-warning text-sm">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>
            {count(data.employees_without_scorecards)} active field staff have no
            scorecard in this window. They are absent from the list below, not
            performing well.
          </span>
        </div>
      )}

      {loading ? (
        <div className="space-y-3">{[1, 2, 3].map(i => <div key={i} className="card animate-pulse h-16" />)}</div>
      ) : !data || data.rows.length === 0 ? (
        <div className="card flex flex-col items-center justify-center py-14 gap-3 text-center">
          <Users className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No individual scorecards recorded in the last {weeks} weeks.
          </p>
        </div>
      ) : (
        <div className="card">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                  <th className="pb-2 pr-4">Employee</th>
                  <th className="pb-2 pr-4">Standing</th>
                  <th className="pb-2 pr-4 text-right">Flagged</th>
                  <th className="pb-2 pr-4 text-right">Weeks</th>
                  <th className="pb-2">Latest</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.rows.map(r => (
                  <tr
                    key={r.employee_id}
                    onClick={() => openDetail(r)}
                    className={`cursor-pointer hover:bg-accent/20 transition-colors ${
                      (r.flagged_metric_count ?? 0) > 0 ? 'bg-danger/5' : ''
                    }`}
                  >
                    <td className="py-2.5 pr-4">
                      <span className="font-medium text-foreground">{r.employee_name}</span>
                      {r.employee_role && (
                        <span className="text-xs text-subtle ml-2 capitalize">{r.employee_role}</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-4">
                      <span className="inline-flex items-center gap-1.5">
                        <Movement dir={r.trend_direction} />
                        <span className={`font-semibold ${standingTone(r.standing)}`}>
                          {r.standing ?? '—'}
                        </span>
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 text-right tabular-nums">
                      {(r.flagged_metric_count ?? 0) > 0
                        ? <span className="text-danger font-semibold">{count(r.flagged_metric_count)}</span>
                        : <span className="text-subtle">0</span>}
                    </td>
                    <td className="py-2.5 pr-4 text-right tabular-nums text-muted-foreground">
                      {count(r.weeks_recorded)}
                    </td>
                    <td className="py-2.5 text-muted-foreground tabular-nums">{r.latest_week ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-subtle">
            Sorted worst first: most flagged metrics, then declining standings.
          </p>
        </div>
      )}

      {detail && <TrendDrawer trend={detail} onClose={() => setDetail(null)} />}
    </div>
  );
}

function TrendDrawer({
  trend, onClose,
}: {
  trend: IndividualTrendResponse;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-6">
      <div className="bg-background border border-border rounded-t-2xl sm:rounded-2xl w-full sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-background border-b border-border px-5 py-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-foreground">{trend.employee_name ?? 'Employee'}</h2>
            <p className="text-xs text-subtle mt-0.5">
              {trend.weeks.length} week{trend.weeks.length === 1 ? '' : 's'} ·
              current standing{' '}
              <span className={standingTone(trend.current_standing)}>
                {trend.current_standing ?? '—'}
              </span>
            </p>
          </div>
          <button onClick={onClose} className="btn-ghost p-1 shrink-0" aria-label="Close">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {(trend.focus_now?.length ?? 0) > 0 && (
            <div className="p-3 rounded-lg bg-danger/10 border border-danger/20">
              <p className="text-xs font-semibold text-danger uppercase tracking-wider mb-1">
                Flagged this week
              </p>
              <p className="text-sm text-foreground">{trend.focus_now!.join(', ')}</p>
            </div>
          )}

          {trend.metrics.length === 0 ? (
            <p className="text-sm text-subtle text-center py-6">No metrics recorded.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border">
                    <th className="pb-2 pr-4">Metric</th>
                    <th className="pb-2 pr-4 text-right">Latest</th>
                    <th className="pb-2 text-right">Change</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {trend.metrics.map(m => {
                    const newest = m.points[m.points.length - 1];
                    return (
                      <tr key={m.key} className={newest?.flag === 'needs_focus' ? 'bg-danger/5' : ''}>
                        <td className="py-2 pr-4 text-foreground">{m.label}</td>
                        <td className="py-2 pr-4 text-right font-semibold text-foreground tabular-nums">
                          {newest?.raw || '—'}
                        </td>
                        <td className="py-2 text-right tabular-nums">
                          {/* Direction is corrected server-side for
                              lower-is-better metrics, so "up" always means
                              improved. Never re-derive it from delta. */}
                          <span className={
                            m.direction === 'up' ? 'text-success'
                            : m.direction === 'down' ? 'text-danger'
                            : 'text-subtle'
                          }>
                            {m.direction === 'up' ? '↑ ' : m.direction === 'down' ? '↓ ' : ''}
                            {m.delta != null ? `${m.delta > 0 ? '+' : ''}${m.delta}` : '—'}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {trend.employee_id && <RetentionSection employeeId={trend.employee_id} />}

        <div className="sticky bottom-0 bg-background border-t border-border px-5 py-3 flex justify-end">
          <button onClick={onClose} className="btn-ghost text-sm">Close</button>
        </div>
      </div>
    </div>
  );
}

/**
 * ADR-492 — retention. Individual scorecards are deleted ~13 months after their
 * week unless held. A scorecard used in a discipline or termination decision
 * must be kept one year from that decision (EEOC 29 CFR 1602.14); an open
 * charge keeps it until released. AsheFlow has no disciplinary record, so the
 * hold is declared here, by the person who made the decision.
 */
function RetentionSection({ employeeId }: { employeeId: string }) {
  const [rows, setRows] = useState<ScorecardRetentionRow[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [kind, setKind] = useState<RetentionHoldIn['kind']>('personnel_decision');
  const [decisionDate, setDecisionDate] = useState(getLocalYMD());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await axiosClient.get<ScorecardRetentionRow[]>(
        `/scorecards/individual/${employeeId}/records`,
      );
      setRows(res.data);
      setSelected(new Set());
    } catch (e) {
      setError(errorText(e, 'Could not load retention status.'));
    }
  }, [employeeId]);

  useEffect(() => { load(); }, [load]);

  const toggle = (id: string) => setSelected(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // One request per scorecard: the server enforces "extend, never shorten" per
  // row, and a refusal on one week must not hide that the others succeeded.
  const hold = async () => {
    setBusy(true);
    setError(null);
    const body: RetentionHoldIn = kind === 'legal_charge'
      ? { kind }
      : { kind, decision_date: decisionDate };
    const failed: string[] = [];
    for (const r of (rows ?? []).filter(r => selected.has(r.id))) {
      try {
        await axiosClient.post(`/scorecards/${r.id}/retention-hold`, body);
      } catch (e) {
        failed.push(`${r.week}: ${errorText(e, 'refused')}`);
      }
    }
    if (failed.length) setError(failed.join(' · '));
    await load();
    setBusy(false);
  };

  const release = async (r: ScorecardRetentionRow) => {
    setBusy(true);
    setError(null);
    try {
      await axiosClient.delete(`/scorecards/${r.id}/retention-hold`);
    } catch (e) {
      setError(errorText(e, `Could not release ${r.week}.`));
    }
    await load();
    setBusy(false);
  };

  const status = (r: ScorecardRetentionRow) => {
    if (r.retention_hold_indefinite) return <span className="text-warning font-medium">Held — open charge</span>;
    if (r.retention_hold_until) return <span className="text-warning font-medium">Held until {formatDate(r.retention_hold_until)}</span>;
    if (r.open_appeal) return <span className="text-muted-foreground">Kept while appeal is open</span>;
    return <span className="text-subtle">Removed after {r.removed_after ? formatDate(r.removed_after) : '—'}</span>;
  };

  return (
    <section className="px-5 pb-5 space-y-3" aria-labelledby="retention-heading">
      <h3 id="retention-heading" className="text-sm font-semibold text-foreground flex items-center gap-2">
        <Lock className="w-4 h-4 text-primary" /> Retention
      </h3>
      <p className="text-xs text-subtle">
        Scorecards are removed about 13 months after their week. If any of these
        informed a discipline or termination decision, hold them: they are then kept
        one year from the decision, or until released if a charge or claim is open.
      </p>

      <ErrorBanner message={error} />

      {rows === null ? (
        <div className="card animate-pulse h-12" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-subtle">No individual scorecards on file.</p>
      ) : (
        <>
          <ul className="divide-y divide-border border border-border rounded-lg">
            {rows.map(r => {
              const held = r.retention_hold_indefinite || !!r.retention_hold_until;
              return (
                <li key={r.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    className="accent-primary"
                    checked={selected.has(r.id)}
                    onChange={() => toggle(r.id)}
                    aria-label={`Select ${r.week}`}
                  />
                  <span className="font-mono text-foreground w-20 shrink-0">{r.week}</span>
                  <span className="flex-1 min-w-0 text-xs">{status(r)}</span>
                  {held && (
                    <button onClick={() => release(r)} disabled={busy} className="btn-ghost text-xs py-1">
                      Release
                    </button>
                  )}
                </li>
              );
            })}
          </ul>

          <div className="flex flex-wrap items-end gap-3">
            <fieldset className="flex flex-col gap-1 text-xs">
              <legend className="sr-only">Hold reason</legend>
              <label className="flex items-center gap-2">
                <input type="radio" name="hold-kind" className="accent-primary"
                  checked={kind === 'personnel_decision'} onChange={() => setKind('personnel_decision')} />
                Discipline or termination decision
              </label>
              <label className="flex items-center gap-2">
                <input type="radio" name="hold-kind" className="accent-primary"
                  checked={kind === 'legal_charge'} onChange={() => setKind('legal_charge')} />
                Open charge or claim
              </label>
            </fieldset>
            {kind === 'personnel_decision' && (
              <label className="text-xs text-muted-foreground flex flex-col gap-1">
                Decision date
                <input
                  type="date"
                  value={decisionDate}
                  max={getLocalYMD()}
                  onChange={e => setDecisionDate(e.target.value)}
                  className="border border-input rounded-lg px-2 py-1 text-sm bg-background"
                />
              </label>
            )}
            <button
              onClick={hold}
              disabled={busy || selected.size === 0}
              className="btn-primary text-sm py-2 flex items-center gap-2"
            >
              {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Hold {selected.size || ''} selected
            </button>
          </div>
        </>
      )}
    </section>
  );
}
