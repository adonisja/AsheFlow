import { useState, useEffect, useCallback } from 'react';
import {
  Building2, CheckCircle2, Lock, AlertTriangle, RefreshCw,
  ChevronDown, ChevronUp, Loader2, FileEdit, Search,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import { SkeletonCard } from '../components/ui/Skeleton';
import type { BuildingProfileResponse, BuildingType } from '../api/types';
import { useAuth } from '../contexts/AuthContext';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BUILDING_TYPE_LABELS: Record<string, string> = {
  receptionist:    'Receptionist',
  walkup:          'Walk-up',
  elevator:        'Elevator',
  biz_freight:     'Business – Freight',
  biz_security:    'Business – Security',
  biz_loading_dock:'Business – Loading Dock',
  mailroom:        'Mailroom',
  doorman:         'Doorman',
  biz_front:       'Business – Front Desk',
};

const BUILDING_TYPES = Object.keys(BUILDING_TYPE_LABELS) as BuildingType[];

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending:  'bg-warning/10 text-warning',
    verified: 'bg-info/10 text-info',
    locked:   'bg-success/10 text-success',
  };
  return (
    <span className={`text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full ${map[status] ?? 'bg-muted text-muted-foreground'}`}>
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Verify modal
// ---------------------------------------------------------------------------

interface VerifyModalProps {
  profile: BuildingProfileResponse;
  onClose: () => void;
  onUpdated: (p: BuildingProfileResponse) => void;
}

function VerifyModal({ profile, onClose, onUpdated }: VerifyModalProps) {
  const [buildingType, setBuildingType] = useState<BuildingType>(profile.building_type as BuildingType);
  const [workloadOverride, setWorkloadOverride] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const { data } = await axiosClient.post<BuildingProfileResponse>(
        `/building-profiles/${profile.id}/verify`,
        {
          confirmed_building_type: buildingType,
          workload_class_override: workloadOverride || null,
        },
      );
      onUpdated(data);
      onClose();
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Verify failed.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-info" />
          <h3 className="font-semibold text-foreground">Verify building type</h3>
        </div>
        <p className="text-xs text-muted-foreground truncate">{profile.normalised_address}</p>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Confirmed type</label>
            <select
              className="input w-full"
              value={buildingType}
              onChange={e => setBuildingType(e.target.value as BuildingType)}
            >
              {BUILDING_TYPES.map(t => (
                <option key={t} value={t}>{BUILDING_TYPE_LABELS[t]}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Workload override (optional)</label>
            <select
              className="input w-full"
              value={workloadOverride}
              onChange={e => setWorkloadOverride(e.target.value)}
            >
              <option value="">Use default</option>
              <option value="standard">Standard</option>
              <option value="heavy">Heavy</option>
              <option value="light">Light</option>
            </select>
          </div>
        </div>
        {profile.raw_note && (
          <div className="p-2 bg-accent/50 rounded-lg text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Walker note: </span>{profile.raw_note}
          </div>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={saving} className="btn-primary text-sm flex items-center gap-1.5">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Verify
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Note modal
// ---------------------------------------------------------------------------

interface NoteModalProps {
  profile: BuildingProfileResponse;
  onClose: () => void;
  onUpdated: (p: BuildingProfileResponse) => void;
}

function NoteModal({ profile, onClose, onUpdated }: NoteModalProps) {
  const [note, setNote] = useState(profile.operational_note ?? profile.raw_note ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const { data } = await axiosClient.patch<BuildingProfileResponse>(
        `/building-profiles/${profile.id}/note`,
        { operational_note: note.trim() },
      );
      onUpdated(data);
      onClose();
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Note update failed.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <FileEdit className="w-4 h-4 text-primary" />
          <h3 className="font-semibold text-foreground">Set operational note</h3>
        </div>
        <p className="text-xs text-muted-foreground truncate">{profile.normalised_address}</p>
        {profile.raw_note && (
          <div className="p-2 bg-accent/50 rounded-lg text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Walker note: </span>{profile.raw_note}
          </div>
        )}
        <textarea
          className="input w-full h-24 resize-none"
          placeholder="Operational note walkers will see at this stop…"
          value={note}
          onChange={e => setNote(e.target.value)}
        />
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={saving || !note.trim()} className="btn-primary text-sm flex items-center gap-1.5">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Save note
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Profile card
// ---------------------------------------------------------------------------

interface ProfileCardProps {
  profile: BuildingProfileResponse;
  canLock: boolean;
  onVerify: (p: BuildingProfileResponse) => void;
  onNote: (p: BuildingProfileResponse) => void;
  onLock: (p: BuildingProfileResponse) => void;
  onUpdated: (p: BuildingProfileResponse) => void;
}

function ProfileCard({ profile, canLock, onVerify, onNote, onLock }: ProfileCardProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-accent/30 transition-colors text-left"
      >
        <Building2 className="w-4 h-4 text-muted-foreground shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">{profile.normalised_address}</p>
          <p className="text-xs text-muted-foreground">
            {BUILDING_TYPE_LABELS[profile.building_type] ?? profile.building_type}
            {' · '}{profile.workload_class}
            {' · '}{profile.block_key}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <StatusPill status={profile.building_type_status} />
          <span className="text-xs text-muted-foreground">{profile.building_type_agreement_count}✓</span>
          {open ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
        </div>
      </button>

      {open && (
        <div className="border-t border-border px-4 py-3 bg-surface/40 space-y-3">
          {/* Notes */}
          {profile.raw_note && (
            <div className="space-y-0.5">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Walker note</p>
              <p className="text-xs text-foreground">{profile.raw_note}</p>
            </div>
          )}
          {profile.operational_note && (
            <div className="space-y-0.5">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold flex items-center gap-1">
                Operational note {profile.note_verified && <CheckCircle2 className="w-3 h-3 text-success" />}
              </p>
              <p className="text-xs text-foreground">{profile.operational_note}</p>
            </div>
          )}

          <p className="text-xs text-muted-foreground">Submitted by {profile.submitted_by_name} · {new Date(profile.created_at).toLocaleDateString()}</p>

          {/* Actions */}
          <div className="flex flex-wrap gap-2 pt-1">
            {profile.building_type_status !== 'locked' && (
              <button
                onClick={() => onVerify(profile)}
                className="text-xs btn-secondary flex items-center gap-1"
              >
                <CheckCircle2 className="w-3.5 h-3.5" /> Verify
              </button>
            )}
            <button
              onClick={() => onNote(profile)}
              className="text-xs btn-secondary flex items-center gap-1"
            >
              <FileEdit className="w-3.5 h-3.5" /> {profile.operational_note ? 'Edit note' : 'Add note'}
            </button>
            {canLock && profile.building_type_status === 'verified' && (
              <button
                onClick={() => onLock(profile)}
                className="text-xs btn-primary flex items-center gap-1"
              >
                <Lock className="w-3.5 h-3.5" /> Lock
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function BuildingProfilesPage() {
  const { groups } = useAuth();

  const [profiles, setProfiles]   = useState<BuildingProfileResponse[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [search, setSearch]       = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'pending' | 'verified' | 'locked'>('all');
  const [lockBusy, setLockBusy]   = useState<string | null>(null);
  const [lockError, setLockError] = useState<string | null>(null);

  // Modal state
  const [verifyTarget, setVerifyTarget] = useState<BuildingProfileResponse | null>(null);
  const [noteTarget,   setNoteTarget]   = useState<BuildingProfileResponse | null>(null);

  const canLock = groups.some(r => ['dispatch', 'management', 'admin'].includes(r));

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await axiosClient.get<BuildingProfileResponse[]>('/building-profiles/');
      setProfiles(data);
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to load building profiles.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function applyUpdate(updated: BuildingProfileResponse) {
    setProfiles(prev => prev.map(p => p.id === updated.id ? updated : p));
  }

  async function handleLock(profile: BuildingProfileResponse) {
    setLockBusy(profile.id);
    setLockError(null);
    try {
      const { data } = await axiosClient.post<BuildingProfileResponse>(`/building-profiles/${profile.id}/lock`);
      applyUpdate(data);
    } catch (e: any) {
      setLockError(e?.response?.data?.detail ?? 'Lock failed.');
    } finally {
      setLockBusy(null);
    }
  }

  const filtered = profiles.filter(p => {
    const matchesStatus = statusFilter === 'all' || p.building_type_status === statusFilter;
    const q = search.toLowerCase();
    const matchesSearch = !q ||
      p.normalised_address.toLowerCase().includes(q) ||
      p.block_key.toLowerCase().includes(q) ||
      (BUILDING_TYPE_LABELS[p.building_type] ?? '').toLowerCase().includes(q);
    return matchesStatus && matchesSearch;
  });

  const pendingCount  = profiles.filter(p => p.building_type_status === 'pending').length;
  const verifiedCount = profiles.filter(p => p.building_type_status === 'verified').length;
  const lockedCount   = profiles.filter(p => p.building_type_status === 'locked').length;

  return (
    <div className="space-y-6 animate-slide-up">
      <SectionHeader
        eyebrow="Address Intelligence"
        title="Building Profiles"
        description="Review and verify walker-submitted building type observations"
        actions={
          <button onClick={load} className="btn-ghost flex items-center gap-1.5 text-sm">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      {/* Summary counts */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Pending',  count: pendingCount,  color: 'text-warning',  filter: 'pending'  },
          { label: 'Verified', count: verifiedCount, color: 'text-info',     filter: 'verified' },
          { label: 'Locked',   count: lockedCount,   color: 'text-success',  filter: 'locked'   },
        ].map(({ label, count, color, filter }) => (
          <button
            key={label}
            onClick={() => setStatusFilter(prev => prev === filter ? 'all' : filter as typeof statusFilter)}
            className={`card text-center py-3 transition-colors hover:bg-accent/50 ${statusFilter === filter ? 'ring-2 ring-primary/30' : ''}`}
          >
            <p className={`text-xl font-bold ${color}`}>{count}</p>
            <p className="text-xs text-muted-foreground">{label}</p>
          </button>
        ))}
      </div>

      {/* Search + filter bar */}
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            type="text"
            className="input pl-8 w-full"
            placeholder="Search address, block key, or type…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      {lockError && (
        <div className="p-3 bg-danger/5 border border-danger/20 rounded-xl text-xs text-danger flex items-center gap-2">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" /> {lockError}
        </div>
      )}

      {error && (
        <div className="p-4 bg-danger/5 border border-danger/20 rounded-xl text-sm text-danger">{error}</div>
      )}

      {/* Profile list */}
      {loading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map(i => <SkeletonCard key={i} />)}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card text-center py-12 space-y-2">
          <Building2 className="w-8 h-8 text-muted-foreground mx-auto" />
          <p className="text-muted-foreground text-sm">
            {profiles.length === 0 ? 'No building profiles submitted yet.' : 'No profiles match your filter.'}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map(p => (
            <div key={p.id} className="relative">
              <ProfileCard
                profile={p}
                canLock={canLock}
                onVerify={setVerifyTarget}
                onNote={setNoteTarget}
                onLock={handleLock}
                onUpdated={applyUpdate}
              />
              {lockBusy === p.id && (
                <div className="absolute inset-0 flex items-center justify-center bg-background/60 rounded-xl">
                  <Loader2 className="w-5 h-5 animate-spin text-primary" />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Modals */}
      {verifyTarget && (
        <VerifyModal
          profile={verifyTarget}
          onClose={() => setVerifyTarget(null)}
          onUpdated={p => { applyUpdate(p); setVerifyTarget(null); }}
        />
      )}
      {noteTarget && (
        <NoteModal
          profile={noteTarget}
          onClose={() => setNoteTarget(null)}
          onUpdated={p => { applyUpdate(p); setNoteTarget(null); }}
        />
      )}
    </div>
  );
}
