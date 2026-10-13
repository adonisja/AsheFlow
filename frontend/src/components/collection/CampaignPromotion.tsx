/**
 * Review a campaign's doors and promote them into building profiles (ADR-495).
 *
 * Company view only (management, admin). Each door is decided once: promote
 * or reject. A promoted door enters Building Profiles as `pending` or
 * `review` — field evidence, not a verified record — and only the company's
 * own sign-off and lock let it reach routing.
 *
 * Nothing is preselected. "Select every ready door" is one click, but a click
 * the reviewer makes: a default of "promote everything" would turn opening the
 * panel into a decision.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, Check, Loader2, X } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../ui/ErrorBanner';
import { errorText } from '../../utils/errorText';
import type {
  PromoteResult, PromotionDecision, PromotionDoor, PromotionDoorState,
} from '../../api/types';

const STATE_LABEL: Record<PromotionDoorState, string> = {
  ready: 'Ready',
  conflict: 'Observations disagree',
  exists: 'Already in your profiles',
  check_address: 'Check the address',
  already_reviewed: 'Done',
};

const STATE_HELP: Record<PromotionDoorState, string> = {
  ready: '',
  conflict: 'Pick the observation that is right. It enters as one observation.',
  exists: 'Your existing profile is kept as it is. Promoting marks this door done.',
  check_address: 'No street name, or one was dropped while tidying it. It names no building, so reject it.',
  already_reviewed: '',
};

const BATCH = 500;   // the server's per-request ceiling

type Choice = { action: 'promote' | 'reject'; rowId?: string };

export default function CampaignPromotion({ tokenId, label, onClose }: {
  tokenId: string;
  label: string;
  onClose: () => void;
}) {
  const [doors, setDoors] = useState<PromotionDoor[] | null>(null);
  const [choices, setChoices] = useState<Record<string, Choice>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PromoteResult | null>(null);
  const [showDone, setShowDone] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const { data } = await axiosClient.get<PromotionDoor[]>(
        `/collection/tokens/${tokenId}/promotion`);
      setDoors(data);
      setChoices({});
    } catch (e) {
      setError(errorText(e, 'Could not load this campaign for review.'));
    }
  }, [tokenId]);

  useEffect(() => { void load(); }, [load]);

  const open = useMemo(() => (doors ?? []).filter(d => d.state !== 'already_reviewed'), [doors]);
  const done = useMemo(() => (doors ?? []).filter(d => d.state === 'already_reviewed'), [doors]);
  const decided = Object.keys(choices).length;

  const choose = (key: string, c: Choice | null) =>
    setChoices(prev => {
      const next = { ...prev };
      if (c) next[key] = c; else delete next[key];
      return next;
    });

  const selectReady = () =>
    setChoices(prev => {
      const next = { ...prev };
      for (const d of open) if (d.state === 'ready' && !next[d.door_key]) {
        next[d.door_key] = { action: 'promote' };
      }
      return next;
    });

  const submit = async () => {
    const decisions: PromotionDecision[] = Object.entries(choices).map(([door_key, c]) => ({
      door_key, action: c.action, ...(c.rowId ? { use_row_id: c.rowId } : {}),
    }));
    setBusy(true);
    setError(null);
    const total: PromoteResult = { promoted: 0, rejected: 0, skipped: 0, outcomes: [] };
    try {
      for (let i = 0; i < decisions.length; i += BATCH) {
        const { data } = await axiosClient.post<PromoteResult>(
          `/collection/tokens/${tokenId}/promote`, { decisions: decisions.slice(i, i + BATCH) });
        total.promoted += data.promoted;
        total.rejected += data.rejected;
        total.skipped += data.skipped;
        total.outcomes.push(...data.outcomes);
      }
      setResult(total);
    } catch (e) {
      // Batches already sent are committed; the reload below shows exactly
      // which doors are now done, so nothing is guessed.
      setError(errorText(e, 'Promotion stopped part-way. The list below shows what was saved.'));
    } finally {
      setBusy(false);
      await load();
    }
  };

  const unresolved = result?.outcomes.filter(
    o => !['promoted', 'rejected', 'skipped'].includes(o.outcome)).length ?? 0;

  return (
    <section className="card p-4 space-y-4" aria-label={`Promote ${label}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold flex items-center gap-1.5">
            <ArrowUpRight className="w-4 h-4" /> Promote to building profiles
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {label}. Promoted doors enter Building Profiles waiting for sign-off. They
            do not affect routing until a route lead verifies and locks them.
          </p>
        </div>
        <button type="button" onClick={onClose} className="btn-ghost p-1.5" aria-label="Close review">
          <X className="w-4 h-4" />
        </button>
      </div>

      <ErrorBanner message={error} />

      {result && (
        <p className="text-sm text-success" role="status">
          Promoted {result.promoted}, rejected {result.rejected}, already had {result.skipped}.
          {unresolved > 0 && ` ${unresolved} door${unresolved === 1 ? '' : 's'} still need a decision.`}
        </p>
      )}

      {doors === null ? (
        <p className="text-sm text-muted-foreground flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading doors…
        </p>
      ) : open.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Every door in this campaign has been reviewed.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">
              {open.length} to review · {decided} decided
            </span>
            <button type="button" onClick={selectReady} className="btn-secondary px-2 py-1 text-xs">
              Select every ready door
            </button>
            {decided > 0 && (
              <button type="button" onClick={() => setChoices({})} className="btn-ghost px-2 py-1 text-xs">
                Clear
              </button>
            )}
          </div>

          <ul className="divide-y divide-border rounded-lg border border-border">
            {open.map(d => (
              <DoorRow key={d.door_key} door={d} choice={choices[d.door_key]}
                onChoose={c => choose(d.door_key, c)} />
            ))}
          </ul>

          <div className="flex justify-end">
            <button type="button" onClick={() => void submit()} disabled={busy || decided === 0}
              className="btn-primary text-sm inline-flex items-center gap-2">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              Apply {decided} decision{decided === 1 ? '' : 's'}
            </button>
          </div>
        </>
      )}

      {done.length > 0 && (
        <details open={showDone} onToggle={e => setShowDone((e.target as HTMLDetailsElement).open)}>
          <summary className="cursor-pointer text-xs text-muted-foreground">
            {done.length} reviewed door{done.length === 1 ? '' : 's'}
          </summary>
          <ul className="mt-2 space-y-1 text-xs">
            {done.map(d => (
              <li key={d.door_key} className="flex justify-between gap-2">
                <span className="truncate">{d.address}</span>
                <span className="text-muted-foreground">{d.rows[0]?.review_status}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

function DoorRow({ door, choice, onChoose }: {
  door: PromotionDoor;
  choice: Choice | undefined;
  onChoose: (c: Choice | null) => void;
}) {
  const pending = door.rows.filter(r => r.review_status === 'pending');
  const conflict = door.state === 'conflict';
  const canPromote = door.state !== 'check_address' && (!conflict || !!choice?.rowId);
  const name = `door-${door.door_key}`;

  return (
    <li className="p-3 space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium truncate">{door.address}</p>
          <p className="text-[11px] text-muted-foreground">
            <span className={door.state === 'ready' ? '' : 'text-warning'}>{STATE_LABEL[door.state]}</span>
            {' · '}{door.observers} observer{door.observers === 1 ? '' : 's'}
          </p>
          {STATE_HELP[door.state] && (
            <p className="text-[11px] text-muted-foreground mt-0.5">{STATE_HELP[door.state]}</p>
          )}
        </div>
        <div className="flex gap-1.5" role="group" aria-label={`Decision for ${door.address}`}>
          <button type="button" disabled={!canPromote && choice?.action !== 'promote'}
            aria-pressed={choice?.action === 'promote'}
            onClick={() => onChoose(choice?.action === 'promote' ? null
              : { action: 'promote', rowId: choice?.rowId })}
            className={`px-2 py-1 text-xs rounded-md border ${choice?.action === 'promote'
              ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-muted'} disabled:opacity-40`}>
            {door.state === 'exists' ? 'Mark done' : 'Promote'}
          </button>
          <button type="button" aria-pressed={choice?.action === 'reject'}
            onClick={() => onChoose(choice?.action === 'reject' ? null : { action: 'reject' })}
            className={`px-2 py-1 text-xs rounded-md border ${choice?.action === 'reject'
              ? 'border-danger bg-danger/10 text-danger' : 'border-border hover:bg-muted'}`}>
            Reject
          </button>
        </div>
      </div>

      <ul className="space-y-1">
        {pending.map(r => (
          <li key={r.id} className="text-xs text-subtle flex items-start gap-2">
            {conflict && (
              <input type="radio" name={name} className="mt-0.5 accent-primary"
                aria-label={`Use ${r.building_type} from ${r.collected_on}`}
                checked={choice?.rowId === r.id}
                onChange={() => onChoose({ action: 'promote', rowId: r.id })} />
            )}
            <span className="min-w-0">
              <span className="font-medium text-foreground">{r.building_type.replace(/_/g, ' ')}</span>
              {r.workloads.length > 0 && ` · ${r.workloads.join(', ').replace(/_/g, ' ')}`}
              {r.has_security_desk && ' · security desk'}
              {` · ${r.collected_on}`}
              {r.address !== door.address && <span className="text-muted-foreground"> · typed “{r.address}”</span>}
              {r.note && <span className="block text-muted-foreground">“{r.note}”</span>}
            </span>
          </li>
        ))}
      </ul>
    </li>
  );
}
