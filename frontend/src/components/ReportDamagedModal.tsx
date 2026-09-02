import { useState } from 'react';
import { X } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { errorText } from '../utils/errorText';
import type { DamagedPackageCreate, DamageStage } from '../api/types';

const STAGE_OPTIONS: { value: DamageStage; label: string }[] = [
  { value: 'station_sort', label: 'Station sort' },
  { value: 'truck_load', label: 'Truck load' },
  { value: 'in_truck', label: 'In truck' },
];

interface ReportDamagedModalProps {
  routeDate: string;                    // YYYY-MM-DD
  defaultStage: DamageStage;            // preset per page: Sort → station_sort, AP Sort → truck_load
  truckAssignmentId?: string | null;    // known on AP Sort; omitted at station
  onClose: () => void;
  onSubmitted?: () => void;
}

export default function ReportDamagedModal({
  routeDate, defaultStage, truckAssignmentId, onClose, onSubmitted,
}: ReportDamagedModalProps) {
  const [tba, setTba] = useState('');
  const [bagId, setBagId] = useState('');
  const [stage, setStage] = useState<DamageStage>(defaultStage);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const body: DamagedPackageCreate = {
        route_date: routeDate,
        tba_number: tba.trim(),
        stage,
        damage_notes: notes.trim(),
        bag_id: bagId.trim() || null,
        truck_assignment_id: truckAssignmentId ?? null,
      };
      await axiosClient.post('/rts/damaged', body);
      onSubmitted?.();
      onClose();
    } catch (e) {
      setError(errorText(e, 'Failed to report damaged package.'));
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        className="bg-card border border-border rounded-2xl shadow-xl w-full max-w-md p-5"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-foreground">Report damaged package</h3>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-muted-foreground mb-4">
          For damage found before a route exists. Pulls the package from the
          flow, and dispatch will follow up. Damage discovered at delivery goes through RTS instead.
        </p>

        {error && (
          <p className="text-xs text-danger bg-danger/10 border border-danger/20 rounded-lg px-3 py-2 mb-3">
            {error}
          </p>
        )}

        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted-foreground">TBA number</label>
            <input
              value={tba}
              onChange={e => setTba(e.target.value)}
              placeholder="TBA…"
              className="input w-full mt-1"
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Bag / tote ID (optional)</label>
            <input
              value={bagId}
              onChange={e => setBagId(e.target.value)}
              placeholder="e.g. BG0012"
              className="input w-full mt-1"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Where found</label>
            <select
              value={stage}
              onChange={e => setStage(e.target.value as DamageStage)}
              className="input w-full mt-1"
            >
              {STAGE_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground">Damage notes</label>
            <textarea
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="What's damaged and how (required)"
              className="input w-full mt-1"
              rows={3}
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="btn btn-ghost">Cancel</button>
          <button
            onClick={submit}
            disabled={submitting || !tba.trim() || !notes.trim()}
            className="btn btn-primary"
          >
            {submitting ? 'Reporting…' : 'Report damaged'}
          </button>
        </div>
      </div>
    </div>
  );
}
