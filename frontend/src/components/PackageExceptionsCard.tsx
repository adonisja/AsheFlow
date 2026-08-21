import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, PackageX } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import type { DamagedPackageResponse, MissingQueueEntry } from '../api/types';

const STAGE_LABELS: Record<string, string> = {
  station_sort: 'Station sort',
  truck_load: 'Truck load',
  in_truck: 'In truck',
};

// found_misroute is deliberately not offered here — it requires a linked
// misroute flag and resolves through the misroute workflow (ADR-190).
const MISSING_RESOLUTIONS = [
  { value: 'found_other', label: 'Found elsewhere' },
  { value: 'confirmed_missing', label: 'Confirmed missing' },
] as const;

interface ResolveState {
  id: string;
  kind: 'missing' | 'damaged';
  resolution?: string;
  notes: string;
  submitting: boolean;
}

export default function PackageExceptionsCard() {
  const [missing, setMissing] = useState<MissingQueueEntry[]>([]);
  const [damaged, setDamaged] = useState<DamagedPackageResponse[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [resolve, setResolve] = useState<ResolveState | null>(null);

  const fetchQueues = () => {
    Promise.allSettled([
      axiosClient.get('/rts/missing').then(r => setMissing(r.data)),
      axiosClient.get('/rts/damaged').then(r => setDamaged(r.data)),
    ]);
  };
  useEffect(() => { fetchQueues(); }, []);

  const submitResolve = async () => {
    if (!resolve) return;
    setError(null);
    setResolve({ ...resolve, submitting: true });
    try {
      if (resolve.kind === 'missing') {
        await axiosClient.patch(`/rts/missing/${resolve.id}/resolve`, {
          resolution_status: resolve.resolution,
          resolution_notes: resolve.notes,
        });
        setMissing(prev => prev.filter(m => m.id !== resolve.id));
      } else {
        await axiosClient.patch(`/rts/damaged/${resolve.id}/resolve`, {
          resolution_notes: resolve.notes,
        });
        setDamaged(prev => prev.filter(d => d.id !== resolve.id));
      }
      setResolve(null);
    } catch (e) {
      setError(errorText(e, 'Failed to resolve report.'));
      setResolve(prev => (prev ? { ...prev, submitting: false } : null));
    }
  };

  const total = missing.length + damaged.length;

  return (
    <div>
      <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
        <PackageX className="w-5 h-5 text-danger" />
        <h2 className="text-base font-semibold text-foreground">Package Exceptions</h2>
        {total > 0 && <span className="ml-auto badge badge-danger">{total}</span>}
      </div>

      <p className="text-xs text-muted-foreground mb-3">
        Unresolved missing package reports from walkers and open damage reports from the
        sort/load floor. Resolve each with notes once accounted for.
      </p>

      {error && (
        <p className="text-xs text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2 mb-3">
          {error}
        </p>
      )}

      {total === 0 ? (
        <div className="text-center py-6 opacity-60">
          <CheckCircle2 className="w-8 h-8 mb-2 text-success mx-auto" />
          <p className="text-sm font-medium">No open package exceptions.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {missing.map(m => (
            <div key={m.id} className="p-3 rounded-xl border border-danger/30 bg-danger/5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground">Missing — {m.tba_number}</p>
                  <p className="text-xs text-muted-foreground">
                    Route {m.route_number ?? '?'}{m.route_date ? ` · ${m.route_date}` : ''}
                    {m.walker_name ? ` · reported by ${m.walker_name}` : ''}
                  </p>
                </div>
                {resolve?.id !== m.id && (
                  <button
                    onClick={() => setResolve({ id: m.id, kind: 'missing', resolution: 'found_other', notes: '', submitting: false })}
                    className="btn btn-sm btn-outline shrink-0"
                  >
                    Resolve
                  </button>
                )}
              </div>
              {resolve?.id === m.id && (
                <div className="mt-2 space-y-2">
                  <select
                    value={resolve.resolution}
                    onChange={e => setResolve({ ...resolve, resolution: e.target.value })}
                    className="input input-sm w-full"
                  >
                    {MISSING_RESOLUTIONS.map(o => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <textarea
                    value={resolve.notes}
                    onChange={e => setResolve({ ...resolve, notes: e.target.value })}
                    placeholder="Resolution notes (required)"
                    className="input w-full text-sm"
                    rows={2}
                  />
                  <div className="flex gap-2 justify-end">
                    <button onClick={() => setResolve(null)} className="btn btn-sm btn-ghost">Cancel</button>
                    <button
                      onClick={submitResolve}
                      disabled={resolve.submitting || !resolve.notes.trim()}
                      className="btn btn-sm btn-primary"
                    >
                      {resolve.submitting ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}

          {damaged.map(d => (
            <div key={d.id} className="p-3 rounded-xl border border-warning/30 bg-warning/5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground flex items-center gap-1.5">
                    <AlertTriangle className="w-3.5 h-3.5 text-warning" />
                    Damaged — {d.tba_number}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {STAGE_LABELS[d.stage] ?? d.stage} · {d.route_date}
                    {d.reported_by_name ? ` · reported by ${d.reported_by_name}` : ''}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">{d.damage_notes}</p>
                </div>
                {resolve?.id !== d.id && (
                  <button
                    onClick={() => setResolve({ id: d.id, kind: 'damaged', notes: '', submitting: false })}
                    className="btn btn-sm btn-outline shrink-0"
                  >
                    Resolve
                  </button>
                )}
              </div>
              {resolve?.id === d.id && (
                <div className="mt-2 space-y-2">
                  <textarea
                    value={resolve.notes}
                    onChange={e => setResolve({ ...resolve, notes: e.target.value })}
                    placeholder="Resolution notes (required)"
                    className="input w-full text-sm"
                    rows={2}
                  />
                  <div className="flex gap-2 justify-end">
                    <button onClick={() => setResolve(null)} className="btn btn-sm btn-ghost">Cancel</button>
                    <button
                      onClick={submitResolve}
                      disabled={resolve.submitting || !resolve.notes.trim()}
                      className="btn btn-sm btn-primary"
                    >
                      {resolve.submitting ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
