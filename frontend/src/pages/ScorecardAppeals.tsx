/**
 * Scorecard appeals (ADR-243).
 *
 * A DSP disputes Amazon's weekly figures when its own records disagree — a DNR
 * counted against us that our RTS log shows was customer-unavailable. Money
 * rides on the correction, so this is a tracked record, not a note.
 *
 * AsheFlow does NOT file with Amazon: a human does that in Amazon's portal.
 * "Mark as filed" records that it happened; the outcome is entered when Amazon
 * responds. The UI says so explicitly, because a button labelled "Submit" on a
 * system that cannot submit is a lie.
 *
 * Tier 4 (docs/SCORECARD_ACCESS_MODEL.md): management and admin only.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Gavel, RefreshCw, Plus, Trophy, XCircle, Clock, FileText, Send,
  ChevronRight, AlertTriangle, TrendingUp, Ban,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import ErrorBanner from '../components/ui/ErrorBanner';
import type {
  AppealListItem, AppealOut, AppealStats, AppealItemOut,
} from '../api/types';
import { count, pct, shortDate } from '../utils/metric';

type StatusFilter = 'all' | 'draft' | 'submitted' | 'won' | 'lost' | 'withdrawn';

const STATUS_TONE: Record<string, string> = {
  draft:     'bg-accent text-muted-foreground border-border',
  submitted: 'bg-info/10 text-info border-info/20',
  won:       'bg-success/10 text-success border-success/20',
  lost:      'bg-danger/10 text-danger border-danger/20',
  withdrawn: 'bg-accent text-muted-foreground border-border',
};

const ITEM_TONE: Record<string, string> = {
  pending:  'bg-accent text-muted-foreground border-border',
  accepted: 'bg-success/10 text-success border-success/20',
  rejected: 'bg-danger/10 text-danger border-danger/20',
};

export default function ScorecardAppeals() {
  const [rows, setRows] = useState<AppealListItem[]>([]);
  const [stats, setStats] = useState<AppealStats | null>(null);
  const [selected, setSelected] = useState<AppealOut | null>(null);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = filter === 'all' ? '' : `?status=${filter}`;
      const [listRes, statsRes] = await Promise.all([
        axiosClient.get<AppealListItem[]>(`/scorecard-appeals${qs}`),
        axiosClient.get<AppealStats>('/scorecard-appeals/stats'),
      ]);
      setRows(listRes.data);
      setStats(statsRes.data);
    } catch {
      setError('Failed to load appeals.');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const openAppeal = async (id: string) => {
    try {
      const res = await axiosClient.get<AppealOut>(`/scorecard-appeals/${id}`);
      setSelected(res.data);
    } catch {
      setError('Failed to open that appeal.');
    }
  };

  /** Wraps a state-changing call: surfaces the backend's 409 reason rather than
   *  a generic failure, since every guard here has a specific explanation. */
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      if (selected) await openAppeal(selected.id);
    } catch (err) {
      const e = err as { response?: { data?: { detail?: string } } };
      setError(e.response?.data?.detail ?? 'That action could not be completed.');
    } finally {
      setBusy(false);
    }
  };

  const decided = (stats?.won ?? 0) + (stats?.lost ?? 0);

  const kpis = useMemo(() => ([
    { label: 'Open drafts', value: count(stats?.draft), icon: FileText, tone: 'text-muted-foreground' },
    { label: 'Filed', value: count(stats?.submitted), icon: Send, tone: 'text-info' },
    { label: 'Won', value: count(stats?.won), icon: Trophy, tone: 'text-success' },
    {
      label: 'Win rate',
      // null, not 0% — "nothing resolved yet" is not "we lose everything".
      value: pct(stats?.win_rate_pct),
      icon: TrendingUp,
      tone: 'text-success',
      sub: decided ? `${decided} decided` : 'none decided yet',
    },
  ]), [stats, decided]);

  return (
    <div className="space-y-8 animate-slide-up">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Gavel className="w-5 h-5 text-primary" /> Scorecard Appeals
          </h1>
          <p className="text-subtle mt-1">
            Dispute Amazon's weekly figures where our own records disagree.
          </p>
        </div>
        <button onClick={load} className="btn-ghost flex items-center gap-2 text-sm">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      <ErrorBanner message={error} />

      {/* Outcome summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {kpis.map(k => (
          <div key={k.label} className="card-elevated p-3">
            <div className="flex items-start justify-between gap-2">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wider">{k.label}</p>
                <p className="text-2xl font-bold text-foreground mt-0.5 tabular-nums">{k.value}</p>
                {k.sub && <p className="text-xs text-subtle">{k.sub}</p>}
              </div>
              <k.icon className={`w-5 h-5 shrink-0 ${k.tone}`} />
            </div>
          </div>
        ))}
      </div>

      {/* Which metrics are worth contesting — the reason line items exist */}
      {(stats?.most_appealed_metrics?.length ?? 0) > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          <div className="card">
            <h2 className="text-base font-semibold text-foreground mb-3">Most appealed</h2>
            {stats!.most_appealed_metrics!.map(m => (
              <div key={m.metric} className="flex items-center justify-between py-1">
                <span className="text-sm text-foreground truncate">{m.metric}</span>
                <span className="text-sm font-semibold text-foreground tabular-nums">{count(m.count)}</span>
              </div>
            ))}
          </div>
          <div className="card">
            <h2 className="text-base font-semibold text-foreground mb-3">Most won</h2>
            {(stats?.most_won_metrics?.length ?? 0) === 0 ? (
              <p className="text-sm text-subtle">No metrics accepted yet.</p>
            ) : stats!.most_won_metrics!.map(m => (
              <div key={m.metric} className="flex items-center justify-between py-1">
                <span className="text-sm text-foreground truncate">{m.metric}</span>
                <span className="text-sm font-semibold text-success tabular-nums">{count(m.count)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Filter */}
      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 text-sm w-fit">
        {(['all', 'draft', 'submitted', 'won', 'lost'] as StatusFilter[]).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg font-medium capitalize transition-colors ${
              filter === f ? 'bg-background text-foreground shadow-sm'
                           : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* List */}
      {loading ? (
        <div className="space-y-3">{[1, 2].map(i => <div key={i} className="card animate-pulse h-20" />)}</div>
      ) : rows.length === 0 ? (
        <div className="card flex flex-col items-center justify-center py-14 gap-3 text-center">
          <Gavel className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {filter === 'all' ? 'No appeals yet.' : `No ${filter} appeals.`}
          </p>
          <p className="text-xs text-subtle max-w-md">
            Start one from a scorecard's cross-check, where our figures are
            compared against Amazon's and contestable metrics are flagged.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map(a => (
            <button
              key={a.id}
              onClick={() => openAppeal(a.id)}
              className="card w-full text-left hover:border-primary/40 transition-colors flex items-center gap-3"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-medium text-foreground">{a.title || `Week ${a.week}`}</span>
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${STATUS_TONE[a.status] ?? ''}`}>
                    {a.status}
                  </span>
                  {a.scope === 'individual' && a.employee_name && (
                    <span className="text-xs text-subtle">· {a.employee_name}</span>
                  )}
                </div>
                <p className="text-xs text-subtle mt-0.5 tabular-nums">
                  {a.week} · {count(a.item_count)} metric{a.item_count === 1 ? '' : 's'}
                  {(a.items_accepted ?? 0) > 0 && (
                    <span className="text-success"> · {count(a.items_accepted)} accepted</span>
                  )}
                  {a.submitted_at && ` · filed ${shortDate(a.submitted_at)}`}
                </p>
              </div>
              <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0" />
            </button>
          ))}
        </div>
      )}

      {selected && (
        <AppealDetail
          appeal={selected}
          busy={busy}
          onClose={() => setSelected(null)}
          onAct={act}
        />
      )}
    </div>
  );
}

function AppealDetail({
  appeal, busy, onClose, onAct,
}: {
  appeal: AppealOut;
  busy: boolean;
  onClose: () => void;
  onAct: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const [reference, setReference] = useState('');
  const [notes, setNotes] = useState('');

  const isDraft = appeal.status === 'draft';
  const isFiled = appeal.status === 'submitted';

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-6">
      <div className="bg-background border border-border rounded-t-2xl sm:rounded-2xl w-full sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-background border-b border-border px-5 py-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-foreground">
              {appeal.title || `Week ${appeal.week}`}
            </h2>
            <p className="text-xs text-subtle mt-0.5">
              {appeal.week} · {appeal.scope}
              {appeal.employee_name && ` · ${appeal.employee_name}`}
            </p>
          </div>
          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border shrink-0 ${STATUS_TONE[appeal.status] ?? ''}`}>
            {appeal.status}
          </span>
        </div>

        <div className="p-5 space-y-5">
          {appeal.rationale && (
            <div>
              <p className="text-xs text-subtle uppercase tracking-wider mb-1">Our case</p>
              <p className="text-sm text-foreground whitespace-pre-wrap">{appeal.rationale}</p>
            </div>
          )}

          {/* Contested metrics — per-metric outcomes are the point of the design:
              Amazon can accept one and reject another in the same appeal. */}
          <div>
            <p className="text-xs text-subtle uppercase tracking-wider mb-2">
              Contested metrics ({count(appeal.items?.length)})
            </p>
            <div className="space-y-2">
              {(appeal.items ?? []).map(item => (
                <ItemRow key={item.id} item={item} appealId={appeal.id} canResolve={isFiled} busy={busy} onAct={onAct} />
              ))}
            </div>
          </div>

          {appeal.submitted_at && (
            <p className="text-xs text-subtle">
              Filed {shortDate(appeal.submitted_at)}
              {appeal.submitted_by_name && ` by ${appeal.submitted_by_name}`}
              {appeal.amazon_reference && ` · Amazon ref ${appeal.amazon_reference}`}
            </p>
          )}
          {appeal.resolved_at && (
            <p className="text-xs text-subtle">
              Resolved {shortDate(appeal.resolved_at)}
              {appeal.resolved_by_name && ` by ${appeal.resolved_by_name}`}
              {appeal.outcome_notes && ` — ${appeal.outcome_notes}`}
            </p>
          )}

          {/* Actions. Wording is deliberate: AsheFlow cannot file with Amazon, so
              the control says "Mark as filed", not "Submit". */}
          {isDraft && (
            <div className="border-t border-border pt-4 space-y-3">
              <p className="text-xs text-subtle">
                File this appeal in Amazon's portal first, then record it here.
              </p>
              <input
                value={reference}
                onChange={e => setReference(e.target.value)}
                placeholder="Amazon case reference (optional)"
                className="w-full px-3 py-2 rounded-lg border border-border bg-accent/20 text-sm"
              />
              <div className="flex flex-wrap gap-2">
                <button
                  disabled={busy || (appeal.items?.length ?? 0) === 0}
                  onClick={() => onAct(() =>
                    axiosClient.post(`/scorecard-appeals/${appeal.id}/submit`,
                      { amazon_reference: reference || null }))}
                  className="btn-primary text-sm flex items-center gap-1.5 disabled:opacity-40"
                  title={(appeal.items?.length ?? 0) === 0
                    ? 'Add at least one contested metric first'
                    : undefined}
                >
                  <Send className="w-4 h-4" /> Mark as filed
                </button>
                <button
                  disabled={busy}
                  onClick={() => onAct(() =>
                    axiosClient.post(`/scorecard-appeals/${appeal.id}/resolve`,
                      { outcome: 'withdrawn', outcome_notes: notes || null }))}
                  className="btn-ghost text-sm flex items-center gap-1.5"
                >
                  <Ban className="w-4 h-4" /> Withdraw
                </button>
              </div>
            </div>
          )}

          {isFiled && (
            <div className="border-t border-border pt-4 space-y-3">
              <p className="text-xs text-subtle">Record Amazon's decision.</p>
              <textarea
                value={notes}
                onChange={e => setNotes(e.target.value)}
                placeholder="Outcome notes (optional)"
                rows={2}
                className="w-full px-3 py-2 rounded-lg border border-border bg-accent/20 text-sm"
              />
              <div className="flex flex-wrap gap-2">
                <button
                  disabled={busy}
                  onClick={() => onAct(() =>
                    axiosClient.post(`/scorecard-appeals/${appeal.id}/resolve`,
                      { outcome: 'won', outcome_notes: notes || null }))}
                  className="btn-primary text-sm flex items-center gap-1.5"
                >
                  <Trophy className="w-4 h-4" /> Amazon corrected it
                </button>
                <button
                  disabled={busy}
                  onClick={() => onAct(() =>
                    axiosClient.post(`/scorecard-appeals/${appeal.id}/resolve`,
                      { outcome: 'lost', outcome_notes: notes || null }))}
                  className="btn-ghost text-sm flex items-center gap-1.5"
                >
                  <XCircle className="w-4 h-4" /> Amazon upheld it
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="sticky bottom-0 bg-background border-t border-border px-5 py-3 flex justify-end">
          <button onClick={onClose} className="btn-ghost text-sm">Close</button>
        </div>
      </div>
    </div>
  );
}

function ItemRow({
  item, appealId, canResolve, busy, onAct,
}: {
  item: AppealItemOut;
  appealId: string;
  canResolve: boolean;
  busy: boolean;
  onAct: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const pending = item.outcome === 'pending';

  return (
    <div className="p-3 rounded-lg bg-accent/20 border border-border">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">{item.metric_label}</p>
          <p className="text-xs text-subtle mt-0.5 tabular-nums">
            Amazon <strong className="text-foreground">{item.amazon_value ?? '—'}</strong>
            {' · '}Ours <strong className="text-foreground">{item.our_value ?? '—'}</strong>
            {item.delta != null && ` · Δ ${item.delta > 0 ? '+' : ''}${item.delta}`}
          </p>
        </div>
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border shrink-0 ${ITEM_TONE[item.outcome] ?? ''}`}>
          {item.outcome}
        </span>
      </div>

      {item.claim && <p className="text-xs text-foreground mt-2">{item.claim}</p>}

      {item.corrected_value && (
        <p className="text-xs text-success mt-1 tabular-nums">
          Corrected to {item.corrected_value}
        </p>
      )}

      {canResolve && pending && (
        <div className="flex gap-2 mt-2">
          <button
            disabled={busy}
            onClick={() => onAct(() =>
              axiosClient.patch(`/scorecard-appeals/${appealId}/items/${item.id}`,
                { outcome: 'accepted' }))}
            className="text-xs px-2 py-1 rounded-lg bg-success/10 text-success border border-success/20"
          >
            Accepted
          </button>
          <button
            disabled={busy}
            onClick={() => onAct(() =>
              axiosClient.patch(`/scorecard-appeals/${appealId}/items/${item.id}`,
                { outcome: 'rejected' }))}
            className="text-xs px-2 py-1 rounded-lg bg-danger/10 text-danger border border-danger/20"
          >
            Rejected
          </button>
        </div>
      )}
    </div>
  );
}
