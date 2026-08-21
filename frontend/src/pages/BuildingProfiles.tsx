import { errorText } from '../utils/errorText';
import { useState, useEffect, useCallback } from 'react';
import {
  Building2, CheckCircle2, Lock, AlertTriangle, RefreshCw, Upload,
  ChevronDown, ChevronUp, Loader2, FileEdit, Search, Plus, Info, MapPin,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import { SkeletonCard } from '../components/ui/Skeleton';
import type { BuildingProfileResponse, BuildingProfileCreate, BuildingProfileAnchorPatch, BuildingType } from '../api/types';
import { useAuth } from '../contexts/AuthContext';
import { useCan } from '../hooks/useCan';
import BulkImportModal from '../components/buildings/BulkImportModal';

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
    // ADR-276 D1: the field agreed and it is queued for sign-off — an action
    // someone owns, so it reads as actionable rather than falling through to
    // the inert grey default.
    review:   'bg-primary/10 text-primary',
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
// Submit modal (captain manually registers a building by TBA)
// ---------------------------------------------------------------------------

interface SubmitModalProps {
  onClose: () => void;
  onCreated: (p: BuildingProfileResponse) => void;
}

function SubmitModal({ onClose, onCreated }: SubmitModalProps) {
  const [address, setAddress]           = useState('');
  const [buildingType, setBuildingType] = useState<BuildingType>('walkup');
  const [rawNote, setRawNote]           = useState('');
  const [saving, setSaving]             = useState(false);
  const [error, setError]               = useState<string | null>(null);

  async function submit() {
    const trimmed = address.trim();
    if (!trimmed) { setError('Address is required.'); return; }
    setSaving(true);
    setError(null);
    try {
      const body: BuildingProfileCreate = {
        normalised_address: trimmed,
        building_type: buildingType,
        raw_note: rawNote.trim() || undefined,
      };
      const { data } = await axiosClient.post<BuildingProfileResponse>('/building-profiles/', body);
      onCreated(data);
      onClose();
    } catch (e: unknown) {
      setError(errorText(e, 'Submission failed.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <Plus className="w-4 h-4 text-primary" />
          <h3 className="font-semibold text-foreground">Submit building profile</h3>
        </div>
        <p className="text-xs text-muted-foreground">
          Enter the normalised address exactly as it appears in the manifest (e.g. "433 W 32 ST").
        </p>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Normalised address</label>
            <input
              type="text"
              className="input w-full font-mono"
              placeholder="433 W 32 ST"
              value={address}
              onChange={e => setAddress(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Building type</label>
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
            <label className="text-xs text-muted-foreground mb-1 block">Raw note (optional)</label>
            <textarea
              className="input w-full h-20 resize-none"
              placeholder="Any observation notes…"
              value={rawNote}
              onChange={e => setRawNote(e.target.value)}
            />
          </div>
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
          <button onClick={submit} disabled={saving} className="btn-primary text-sm flex items-center gap-1.5">
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
/** What is still needed to verify, in the reader's own terms (ADR-276 D6).
 *
 *  A bare "1✓" tells a captain nothing about whether THEIR tap finishes it.
 *  The server sends `remaining_weight` and `can_verify`, so this never
 *  re-derives the rule — a client computing `2 - count` would be wrong the
 *  moment a weight changes, and wrong as a button that silently does nothing.
 */
function verifyHint(p: BuildingProfileResponse): string {
  if (p.building_type_status === 'locked')   return 'Locked';
  if (p.remaining_weight == null)            return `${p.building_type_agreement_count}✓`;
  if (p.remaining_weight <= 0)               return 'Verified';
  if (p.building_type_status === 'review')    return 'Awaiting sign-off';
  if (p.remaining_weight >= 2)               return 'Needs 2 walkers, or 1 captain';
  return 'Needs 1 more walker, or 1 captain';
}

/** Why this caller cannot confirm. Absent reason = they can. */
function verifyBlockedText(p: BuildingProfileResponse): string | null {
  switch (p.verify_blocked_reason) {
    case 'own_submission':       return 'You submitted this — someone else must confirm it';
    case 'already_verified':     return 'You already confirmed this';
    case 'awaiting_signoff':     return 'The field agrees — a captain or dispatch signs this off';
    case 'not_a_field_verifier': return 'Only people who walk the blocks can confirm a building';
    default:                 return null;
  }
}

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
    } catch (e: unknown) {
      setError(errorText(e, 'Verify failed.'));
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
              <option value="bulk_drop">Bulk Drop</option>
              <option value="high_touch">High Touch</option>
              <option value="high_wait">High Wait</option>
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
    } catch (e: unknown) {
      setError(errorText(e, 'Note update failed.'));
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
// Anchor point modal (dispatch sets initial anchor)
// ---------------------------------------------------------------------------

interface AnchorModalProps {
  profile: BuildingProfileResponse;
  onClose: () => void;
  onUpdated: (p: BuildingProfileResponse) => void;
}

function AnchorModal({ profile, onClose, onUpdated }: AnchorModalProps) {
  const [lat,  setLat]  = useState(profile.initial_anchor_lat?.toString()  ?? '');
  const [lng,  setLng]  = useState(profile.initial_anchor_lng?.toString()  ?? '');
  const [note, setNote] = useState(profile.initial_anchor_note ?? '');
  const [saving, setSaving] = useState(false);
  const [error,  setError]  = useState<string | null>(null);

  const hasExisting = profile.initial_anchor_lat != null;

  async function save() {
    const latNum = parseFloat(lat);
    const lngNum = parseFloat(lng);
    if (isNaN(latNum) || isNaN(lngNum)) { setError('Enter valid lat/lng coordinates.'); return; }
    if (latNum < -90 || latNum > 90)    { setError('Latitude must be between -90 and 90.'); return; }
    if (lngNum < -180 || lngNum > 180)  { setError('Longitude must be between -180 and 180.'); return; }
    setSaving(true);
    setError(null);
    try {
      const body: BuildingProfileAnchorPatch = { lat: latNum, lng: lngNum, note: note.trim() || null };
      const { data } = await axiosClient.patch<BuildingProfileResponse>(
        `/building-profiles/${profile.id}/anchor`, body,
      );
      onUpdated(data);
      onClose();
    } catch (e: unknown) {
      setError(errorText(e, 'Failed to save anchor point.'));
    } finally {
      setSaving(false);
    }
  }

  async function clear() {
    setSaving(true);
    setError(null);
    try {
      const body: BuildingProfileAnchorPatch = { lat: null, lng: null };
      const { data } = await axiosClient.patch<BuildingProfileResponse>(
        `/building-profiles/${profile.id}/anchor`, body,
      );
      onUpdated(data);
      onClose();
    } catch (e: unknown) {
      setError(errorText(e, 'Failed to clear anchor point.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center gap-2">
          <MapPin className="w-4 h-4 text-primary" />
          <h3 className="font-semibold text-foreground">{hasExisting ? 'Update' : 'Set'} initial anchor point</h3>
        </div>
        <p className="text-xs text-muted-foreground truncate">{profile.normalised_address}</p>
        <p className="text-xs text-muted-foreground">
          This anchor feeds the Field Ops driver AP workflow as a starting location suggestion,
          and provides an anchor hint to the sort pipeline for trucks with no
          configured anchor and no zone history.
        </p>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Latitude</label>
              <input
                type="number"
                step="any"
                className="input w-full font-mono text-sm"
                placeholder="40.7128"
                value={lat}
                onChange={e => setLat(e.target.value)}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">Longitude</label>
              <input
                type="number"
                step="any"
                className="input w-full font-mono text-sm"
                placeholder="-74.0060"
                value={lng}
                onChange={e => setLng(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Label (optional)</label>
            <input
              type="text"
              className="input w-full text-sm"
              placeholder="e.g. Corner of 9th Ave & 34th St"
              maxLength={200}
              value={note}
              onChange={e => setNote(e.target.value)}
            />
          </div>
        </div>
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-between">
          {hasExisting && (
            <button onClick={clear} disabled={saving} className="btn-secondary text-sm text-destructive">
              Clear
            </button>
          )}
          <div className="flex gap-2 ml-auto">
            <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
            <button onClick={save} disabled={saving} className="btn-primary text-sm flex items-center gap-1.5">
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Save anchor
            </button>
          </div>
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
  canAnchor: boolean;
  onVerify: (p: BuildingProfileResponse) => void;
  onNote: (p: BuildingProfileResponse) => void;
  onLock: (p: BuildingProfileResponse) => void;
  onAnchor: (p: BuildingProfileResponse) => void;
  onUpdated: (p: BuildingProfileResponse) => void;
}

function ProfileCard({ profile, canLock, canAnchor, onVerify, onNote, onLock, onAnchor }: ProfileCardProps) {
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
          <span className="text-xs text-muted-foreground">{verifyHint(profile)}</span>
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
          {profile.protocol_reminder && (
            <div className="flex items-start gap-1.5 p-2 bg-info/5 border border-info/20 rounded-lg">
              <Info className="w-3.5 h-3.5 text-info shrink-0 mt-0.5" />
              <p className="text-xs text-info">{profile.protocol_reminder}</p>
            </div>
          )}

          {/* Initial anchor point */}
          {profile.initial_anchor_lat != null ? (
            <div className="space-y-0.5">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold flex items-center gap-1">
                <MapPin className="w-3 h-3" /> Initial anchor point
              </p>
              <p className="text-xs text-foreground font-mono">
                {profile.initial_anchor_lat.toFixed(6)}, {profile.initial_anchor_lng?.toFixed(6)}
              </p>
              {profile.initial_anchor_note && (
                <p className="text-xs text-muted-foreground">{profile.initial_anchor_note}</p>
              )}
              {profile.initial_anchor_set_by_name && (
                <p className="text-[10px] text-muted-foreground">
                  Set by {profile.initial_anchor_set_by_name}
                  {profile.initial_anchor_set_at ? ` · ${new Date(profile.initial_anchor_set_at).toLocaleDateString()}` : ''}
                </p>
              )}
            </div>
          ) : canAnchor && (
            <div className="flex items-center gap-1.5 p-2 bg-accent/30 rounded-lg">
              <MapPin className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
              <p className="text-xs text-muted-foreground">No initial anchor point set — feeds sort pipeline and AP workflow.</p>
            </div>
          )}

          <p className="text-xs text-muted-foreground">Submitted by {profile.submitted_by_name} · {new Date(profile.created_at).toLocaleDateString()}</p>

          {/* Actions */}
          <div className="flex flex-wrap gap-2 pt-1">
            {profile.building_type_status !== 'locked' && (
              <button
                onClick={() => onVerify(profile)}
                disabled={profile.can_verify === false}
                title={verifyBlockedText(profile) ?? 'Confirm this building type'}
                className="text-xs btn-secondary flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
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
            {canAnchor && (
              <button
                onClick={() => onAnchor(profile)}
                className="text-xs btn-secondary flex items-center gap-1"
              >
                <MapPin className="w-3.5 h-3.5" /> {profile.initial_anchor_lat != null ? 'Edit anchor' : 'Set anchor'}
              </button>
            )}
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
  const { can } = useCan();

  const [profiles, setProfiles]   = useState<BuildingProfileResponse[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [search, setSearch]       = useState('');
  /* ADR-276: `review` is the sign-off queue — the field has agreed and a
     captain or dispatch has not signed it off yet. A captain lands on it,
     because that queue IS their job on this page; everyone else sees all. */
  const { groups } = useAuth();
  const isCaptain = groups.includes('captain');
  const [bulkOpen, setBulkOpen] = useState(false);
  // ADR-277 D4: the sign-off roles, matching the endpoint gate. Drivers are
  // excluded — they do not assess buildings.
  const canBulkSeed = ['captain', 'dispatch', 'field_supervisor', 'management', 'admin']
    .some(r => groups.includes(r));
  const [statusFilter, setStatusFilter] =
    useState<'all' | 'pending' | 'review' | 'verified' | 'locked'>(isCaptain ? 'review' : 'all');
  const [lockBusy, setLockBusy]   = useState<string | null>(null);
  const [lockError, setLockError] = useState<string | null>(null);

  // Modal state
  const [submitOpen,    setSubmitOpen]    = useState(false);
  const [verifyTarget,  setVerifyTarget]  = useState<BuildingProfileResponse | null>(null);
  const [noteTarget,    setNoteTarget]    = useState<BuildingProfileResponse | null>(null);
  const [anchorTarget,  setAnchorTarget]  = useState<BuildingProfileResponse | null>(null);

  const canLock   = can('lockBuildingProfile');
  const canAnchor = can('anchorBuildingProfile');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await axiosClient.get<BuildingProfileResponse[]>('/building-profiles/');
      setProfiles(data);
    } catch (e: unknown) {
      setError(errorText(e, 'Failed to load building profiles.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function applyUpdate(updated: BuildingProfileResponse) {
    setProfiles(prev => prev.map(p => p.id === updated.id ? updated : p));
  }

  function handleCreated(profile: BuildingProfileResponse) {
    setProfiles(prev => [profile, ...prev]);
  }

  async function handleLock(profile: BuildingProfileResponse) {
    setLockBusy(profile.id);
    setLockError(null);
    try {
      const { data } = await axiosClient.post<BuildingProfileResponse>(`/building-profiles/${profile.id}/lock`);
      applyUpdate(data);
    } catch (e: unknown) {
      setLockError(errorText(e, 'Lock failed.'));
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
  const reviewCount   = profiles.filter(p => p.building_type_status === 'review').length;
  const verifiedCount = profiles.filter(p => p.building_type_status === 'verified').length;
  const lockedCount   = profiles.filter(p => p.building_type_status === 'locked').length;

  return (
    <div className="space-y-6 animate-slide-up">
      <SectionHeader
        eyebrow="Address Intelligence"
        title="Building Profiles"
        description="Review and verify walker-submitted building type observations"
        actions={
          <div className="flex items-center gap-2">
            <button onClick={() => setSubmitOpen(true)} className="btn-primary flex items-center gap-1.5 text-sm">
              <Plus className="w-4 h-4" /> Submit profile
            </button>
            {canBulkSeed && (
              <button onClick={() => setBulkOpen(true)} className="btn-ghost flex items-center gap-1.5 text-sm">
                <Upload className="w-4 h-4" /> Import CSV
              </button>
            )}
            <button onClick={load} className="btn-ghost flex items-center gap-1.5 text-sm">
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>
          </div>
        }
      />

      {/* Summary counts */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Pending',  count: pendingCount,  color: 'text-warning',  filter: 'pending'  },
          { label: 'Needs sign-off', count: reviewCount, color: 'text-primary', filter: 'review' },
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
                canAnchor={canAnchor}
                onVerify={setVerifyTarget}
                onNote={setNoteTarget}
                onLock={handleLock}
                onAnchor={setAnchorTarget}
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
      {bulkOpen && (
        <BulkImportModal
          onClose={() => setBulkOpen(false)}
          onImported={load}
        />
      )}

      {submitOpen && (
        <SubmitModal
          onClose={() => setSubmitOpen(false)}
          onCreated={handleCreated}
        />
      )}
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
      {anchorTarget && (
        <AnchorModal
          profile={anchorTarget}
          onClose={() => setAnchorTarget(null)}
          onUpdated={p => { applyUpdate(p); setAnchorTarget(null); }}
        />
      )}
    </div>
  );
}
