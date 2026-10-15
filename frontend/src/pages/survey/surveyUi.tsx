/**
 * Small pieces the survey pages share (ADR-513).
 *
 * Progress is shown as a bar with the count beside it (ADR-433: progress over
 * counts), and a block's state always says which kind of "not done" it is.
 */
import type { SurveyBlockState } from '../../api/types';
import { formatDate } from '../../utils/date';

export function ProgressBar({ done, total, label }: { done: number; total: number; label: string }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="h-2 overflow-hidden rounded-full bg-muted" role="progressbar" aria-label={label}
        aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
        <div className="h-full rounded-full bg-primary transition-[width] motion-reduce:transition-none"
          style={{ width: `${pct}%` }} />
      </div>
      <p className="text-xs text-muted-foreground">{done} of {total} {label}</p>
    </div>
  );
}

export function BlockStateBadge({ state, done, total, reopensOn }: {
  state: SurveyBlockState; done: number; total: number; reopensOn: string | null;
}) {
  if (state === 'done') {
    return (
      <span className="rounded-full bg-success/15 px-2 py-0.5 text-xs font-medium text-success">
        Done{reopensOn ? ` · re-opens ${formatDate(reopensOn)}` : ''}
      </span>
    );
  }
  if (state === 'in_progress') {
    return (
      <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs font-medium text-warning">
        In progress · {done} of {total}
      </span>
    );
  }
  return <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">Open · {total} doors</span>;
}

/** "31 h left" / "40 min left": a claim's remaining time, coarse on purpose. */
export function timeLeft(expiresAt: string, now = Date.now()): string {
  const ms = new Date(expiresAt).getTime() - now;
  if (ms <= 0) return 'ended';
  const h = Math.floor(ms / 3_600_000);
  return h >= 1 ? `${h} h left` : `${Math.max(1, Math.round(ms / 60_000))} min left`;
}

export function distanceLabel(m: number | null): string | null {
  if (m == null) return null;
  return m < 1000 ? `${Math.round(m / 10) * 10} m` : `${(m / 1000).toFixed(1)} km`;
}
