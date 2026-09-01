import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, RefreshCw, ShieldAlert } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import SectionHeader from '../../components/ui/SectionHeader';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { SkeletonCard } from '../../components/ui/Skeleton';
import { errorText } from '../../utils/errorText';
import type { PlatformAlert } from '../../api/types';

/**
 * Infrastructure alerts only a super admin can act on (ADR-340).
 *
 * ADR-335 built the table and the endpoints; ADR-337 added the heartbeat that
 * detects a revoked credential within ten minutes. Neither had a reader — the
 * detection improved and the noticing did not, which is the same shape as the
 * original incident where a dead Discord token surfaced only because a
 * dispatcher reported that messages had stopped.
 *
 * Read-only plus resolve, on purpose (ADR-340 D1). The token-rotation form
 * belongs on ADR-324 D3's settings page, which still has two unsolved
 * constraints — building a throwaway form here would either be discarded or
 * become the reason that page never gets designed.
 */

/** Human-readable names for the alert types the platform raises. */
const TYPE_LABELS: Record<string, string> = {
  discord_integration_failed: 'Discord',
  email_delivery_failed: 'Email (SES)',
  identity_revocation_failed: 'Identity revocation (Cognito)',
  backup_failed: 'Database backup',
};

function typeLabel(t: string): string {
  return TYPE_LABELS[t] ?? t.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function fmt(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

/** "3 minutes ago" beats a timestamp for "is this still happening". */
function sinceLabel(iso: string | null): string {
  if (!iso) return '';
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function PlatformAlerts() {
  const [alerts, setAlerts] = useState<PlatformAlert[]>([]);
  const [companies, setCompanies] = useState<Record<string, string>>({});
  const [showResolved, setShowResolved] = useState(false);
  const [loading, setLoading] = useState(true);
  const [resolving, setResolving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [alertRes, coRes] = await Promise.allSettled([
        axiosClient.get<PlatformAlert[]>('/platform/alerts', {
          params: { include_resolved: showResolved },
        }),
        axiosClient.get<{ id: string; name: string }[]>('/admin/companies/'),
      ]);

      if (alertRes.status === 'fulfilled') setAlerts(alertRes.value.data ?? []);
      else setError(errorText(alertRes.reason, 'Failed to load platform alerts.'));

      // A raw UUID tells a reader nothing. Best-effort: if this fails the page
      // still works, it just shows the id.
      if (coRes.status === 'fulfilled') {
        const map: Record<string, string> = {};
        for (const c of coRes.value.data ?? []) map[c.id] = c.name;
        setCompanies(map);
      }
    } finally {
      setLoading(false);
    }
  }, [showResolved]);

  useEffect(() => { load(); }, [load]);

  // The heartbeat runs every 10 minutes (ADR-337), so a slower poll would show
  // stale state; a faster one would poll for data that cannot have changed.
  useEffect(() => {
    const id = setInterval(load, 10 * 60 * 1000);
    return () => clearInterval(id);
  }, [load]);

  const resolve = async (alertId: string) => {
    setResolving(alertId);
    setError(null);
    try {
      await axiosClient.post(`/platform/alerts/${alertId}/resolve`, {});
      await load();
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to resolve that alert.'));
    } finally {
      setResolving(null);
    }
  };

  const open = alerts.filter(a => !a.is_resolved);
  const critical = open.filter(a => a.severity === 'critical');

  return (
    <div className="space-y-6">
      <SectionHeader
        title="Platform Alerts"
        description="Infrastructure conditions only a super admin can fix"
      />

      <ErrorBanner message={error} />

      {/* The headline a super admin needs before reading anything else. */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className={`card px-4 py-3 flex items-center gap-3 ${open.length ? 'border-danger/50' : 'border-success/40'}`}>
          {open.length ? (
            <ShieldAlert className="w-5 h-5 text-danger shrink-0" />
          ) : (
            <CheckCircle2 className="w-5 h-5 text-success shrink-0" />
          )}
          <div>
            <p className="text-sm font-semibold">
              {open.length === 0
                ? 'All integrations healthy'
                : `${open.length} open alert${open.length === 1 ? '' : 's'}`}
            </p>
            <p className="text-xs text-muted-foreground">
              {critical.length > 0
                ? `${critical.length} critical`
                : 'Checked every 10 minutes'}
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={load}
          className="btn-secondary flex items-center gap-2 text-sm"
        >
          <RefreshCw className="w-4 h-4" />
          Refresh
        </button>

        <label className="flex items-center gap-2 text-sm text-muted-foreground ml-auto">
          <input
            type="checkbox"
            checked={showResolved}
            onChange={e => setShowResolved(e.target.checked)}
          />
          Show resolved
        </label>
      </div>

      {loading ? (
        <SkeletonCard />
      ) : alerts.length === 0 ? (
        <div className="card text-center py-16 flex flex-col items-center">
          <CheckCircle2 className="w-10 h-10 text-success mb-4 opacity-40" />
          <p className="text-sm font-medium text-foreground">
            {showResolved ? 'No alerts recorded.' : 'No open alerts.'}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            Discord, email and identity revocation are probed every 10 minutes.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map(a => (
            <div
              key={a.id}
              className={`card space-y-3 ${
                a.is_resolved
                  ? 'opacity-60'
                  : a.severity === 'critical'
                    ? 'border-danger/50 bg-danger/5'
                    : 'border-warning/50 bg-warning/5'
              }`}
            >
              <div className="flex items-start gap-3 flex-wrap">
                <AlertTriangle
                  className={`w-5 h-5 shrink-0 mt-0.5 ${
                    a.is_resolved ? 'text-muted-foreground'
                      : a.severity === 'critical' ? 'text-danger' : 'text-warning'
                  }`}
                />
                <div className="flex-1 min-w-[16rem]">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-sm font-semibold">{typeLabel(a.alert_type)}</h3>
                    {a.severity === 'critical' && !a.is_resolved && (
                      <span className="text-[10px] font-bold uppercase tracking-wide text-danger">
                        Critical
                      </span>
                    )}
                    {a.is_resolved && (
                      <span className="text-[10px] font-semibold uppercase tracking-wide text-success">
                        Resolved
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">{a.message}</p>

                  <p className="text-xs text-muted-foreground mt-2">
                    {/* Scope first: "every tenant" vs "one company" changes the response. */}
                    <span className="font-medium">
                      {a.company_id
                        ? (companies[a.company_id] ?? `Company ${a.company_id.slice(0, 8)}`)
                        : 'All companies'}
                    </span>
                    {' · '}
                    {/* occurrence_count and last_seen are what distinguish "still
                        failing" from "an alert exists" (ADR-335 D2). */}
                    {a.occurrence_count > 1 && `${a.occurrence_count} occurrences · `}
                    first seen {fmt(a.first_seen_at)}
                    {!a.is_resolved && a.last_seen_at && ` · last seen ${sinceLabel(a.last_seen_at)}`}
                    {a.is_resolved && a.resolved_at && ` · resolved ${fmt(a.resolved_at)}`}
                    {a.is_resolved && (
                      a.resolved_by_email
                        ? ` by ${a.resolved_by_email}`
                        : ' automatically — the integration recovered'
                    )}
                  </p>
                </div>

                {!a.is_resolved && (
                  <button
                    type="button"
                    onClick={() => resolve(a.id)}
                    disabled={resolving === a.id}
                    className="btn-secondary text-xs shrink-0 disabled:opacity-50"
                    title="Most alerts clear themselves when the integration recovers. Use this for a condition the heartbeat cannot detect."
                  >
                    {resolving === a.id ? 'Resolving…' : 'Resolve'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
