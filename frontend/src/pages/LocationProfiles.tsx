import React, { useState, useEffect, useCallback } from 'react';
import { Building2, CheckCircle2, Clock, Lock, Plus, RefreshCw, Search, XCircle, AlertTriangle, FileText } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LocationProfile {
  id: string;
  block_key: string;
  building_type: string;
  workload_class: string;
  building_type_status: string;
  building_type_agreement_count: number;
  nomination_status: string | null;
  raw_notes: string | null;
  operational_note: string | null;
  note_verified: boolean;
  submitted_by_name: string;
  submitted_at: string | null;
  verified_by_name: string | null;
  verified_at: string | null;
  protocol_reminder: string;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BUILDING_TYPES = [
  { value: 'mailroom',         label: 'Mailroom',        workload: 'bulk_drop'  },
  { value: 'receptionist',     label: 'Receptionist',    workload: 'bulk_drop'  },
  { value: 'walkup',           label: 'Walk-up',         workload: 'high_touch' },
  { value: 'elevator',         label: 'Elevator',        workload: 'standard'   },
  { value: 'biz_front',        label: 'Biz Front',       workload: 'standard'   },
  { value: 'biz_freight',      label: 'Biz Freight',     workload: 'high_wait'  },
  { value: 'biz_security',     label: 'Biz Security',    workload: 'high_touch' },
  { value: 'biz_loading_dock', label: 'Loading Dock',    workload: 'bulk_drop'  },
];

const STATUS_ORDER = ['pending', 'verified', 'locked'];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  if (status === 'locked') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-success/15 text-success">
        <Lock className="w-3 h-3" /> Locked
      </span>
    );
  }
  if (status === 'verified') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-info/15 text-info">
        <CheckCircle2 className="w-3 h-3" /> Verified
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-accent text-muted-foreground">
      <Clock className="w-3 h-3" /> Pending
    </span>
  );
}

function WorkloadBadge({ workload }: { workload: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    bulk_drop:  { label: 'Bulk Drop',   cls: 'bg-primary/10 text-primary'   },
    high_touch: { label: 'High Touch',  cls: 'bg-warning/15 text-warning'   },
    high_wait:  { label: 'High Wait',   cls: 'bg-danger/10 text-danger'     },
    standard:   { label: 'Standard',    cls: 'bg-accent text-muted-foreground' },
  };
  const w = map[workload] ?? { label: workload, cls: 'bg-accent text-muted-foreground' };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${w.cls}`}>
      {w.label}
    </span>
  );
}

function buildingLabel(type: string) {
  return BUILDING_TYPES.find(b => b.value === type)?.label ?? type;
}

function fmt(iso: string | null) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

// ---------------------------------------------------------------------------
// Submit modal
// ---------------------------------------------------------------------------

function SubmitModal({
  onClose,
  onSubmitted,
}: {
  onClose: () => void;
  onSubmitted: () => void;
}) {
  const [blockKey, setBlockKey] = useState('');
  const [buildingType, setBuildingType] = useState('');
  const [rawNotes, setRawNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!blockKey.trim() || !buildingType) return;
    setSubmitting(true);
    setError('');
    try {
      await axiosClient.post('/location-profiles/', {
        block_key: blockKey.trim(),
        building_type: buildingType,
        raw_notes: rawNotes.trim() || null,
      });
      onSubmitted();
      onClose();
    } catch (err: any) {
      const msg = err?.response?.data?.detail;
      setError(typeof msg === 'string' ? msg : 'Failed to submit. Try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-2xl shadow-xl w-full max-w-md animate-slide-up">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <h2 className="font-semibold text-foreground">Submit Building Profile</h2>
          <button onClick={onClose} className="btn-ghost p-1.5 rounded-lg"><XCircle className="w-4 h-4" /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {error && <ErrorBanner message={error} />}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Block Key</label>
            <input
              className="input w-full"
              placeholder="e.g. W_36_St_410s_odd"
              value={blockKey}
              onChange={e => setBlockKey(e.target.value)}
              required
            />
            <p className="text-xs text-muted-foreground">Format: Street_Range_side. E.g. W_36_St_410s_odd</p>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Building Type</label>
            <select
              className="input w-full"
              value={buildingType}
              onChange={e => setBuildingType(e.target.value)}
              required
            >
              <option value="">Select type…</option>
              {BUILDING_TYPES.map(b => (
                <option key={b.value} value={b.value}>{b.label} — {b.workload}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Notes (optional)</label>
            <textarea
              className="input w-full min-h-[80px] resize-y"
              placeholder="Any delivery notes for this building…"
              value={rawNotes}
              onChange={e => setRawNotes(e.target.value)}
              maxLength={2000}
            />
          </div>
          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn-ghost flex-1">Cancel</button>
            <button type="submit" disabled={submitting} className="btn-primary flex-1">
              {submitting ? 'Submitting…' : 'Submit'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Profile detail panel
// ---------------------------------------------------------------------------

function ProfilePanel({
  profile,
  canVerify,
  onUpdate,
  onClose,
}: {
  profile: LocationProfile;
  canVerify: boolean;
  onUpdate: (updated: LocationProfile) => void;
  onClose: () => void;
}) {
  const [verifyType, setVerifyType] = useState(profile.building_type);
  const [noteText, setNoteText] = useState(profile.operational_note ?? '');
  const [savingNote, setSavingNote] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [verifyingNote, setVerifyingNote] = useState(false);
  const [error, setError] = useState('');

  const handleVerify = async () => {
    setVerifying(true);
    setError('');
    try {
      const res = await axiosClient.post<LocationProfile>(`/location-profiles/${profile.id}/verify`, {
        confirmed_building_type: verifyType,
      });
      onUpdate(res.data);
    } catch (err: any) {
      const msg = err?.response?.data?.detail;
      setError(typeof msg === 'string' ? msg : 'Verification failed.');
    } finally {
      setVerifying(false);
    }
  };

  const handleSaveNote = async () => {
    setSavingNote(true);
    setError('');
    try {
      const res = await axiosClient.patch<LocationProfile>(`/location-profiles/${profile.id}/note`, {
        operational_note: noteText,
      });
      onUpdate(res.data);
    } catch (err: any) {
      const msg = err?.response?.data?.detail;
      setError(typeof msg === 'string' ? msg : 'Failed to save note.');
    } finally {
      setSavingNote(false);
    }
  };

  const handleVerifyNote = async () => {
    setVerifyingNote(true);
    setError('');
    try {
      const res = await axiosClient.post<LocationProfile>(`/location-profiles/${profile.id}/verify-note`);
      onUpdate(res.data);
    } catch (err: any) {
      const msg = err?.response?.data?.detail;
      setError(typeof msg === 'string' ? msg : 'Failed to verify note.');
    } finally {
      setVerifyingNote(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-card border border-border rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto animate-slide-up">
        {/* Header */}
        <div className="flex items-start justify-between px-6 py-4 border-b border-border sticky top-0 bg-card z-10">
          <div>
            <p className="font-mono text-sm font-semibold text-foreground">{profile.block_key}</p>
            <div className="flex items-center gap-2 mt-1">
              <StatusBadge status={profile.building_type_status} />
              <WorkloadBadge workload={profile.workload_class} />
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost p-1.5 rounded-lg shrink-0">
            <XCircle className="w-4 h-4" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {error && <ErrorBanner message={error} />}

          {/* Meta */}
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="text-muted-foreground">Building Type</p>
              <p className="font-medium text-foreground mt-0.5">{buildingLabel(profile.building_type)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Agreements</p>
              <p className="font-medium text-foreground mt-0.5">{profile.building_type_agreement_count}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Submitted by</p>
              <p className="font-medium text-foreground mt-0.5">{profile.submitted_by_name}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Submitted</p>
              <p className="font-medium text-foreground mt-0.5">{fmt(profile.submitted_at)}</p>
            </div>
          </div>

          {/* Protocol reminder */}
          {profile.protocol_reminder && (
            <div className="flex items-start gap-2 p-3 rounded-xl bg-info/10 border border-info/20 text-xs text-info">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
              <span>{profile.protocol_reminder}</span>
            </div>
          )}

          {/* Raw notes */}
          {profile.raw_notes && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Walker Notes</p>
              <p className="text-sm text-foreground bg-accent/40 rounded-xl p-3 whitespace-pre-wrap">{profile.raw_notes}</p>
            </div>
          )}

          {/* Operational note */}
          {canVerify && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Operational Note</p>
                {profile.note_verified && (
                  <span className="inline-flex items-center gap-1 text-xs text-success">
                    <CheckCircle2 className="w-3 h-3" /> Verified by {profile.note_verified_by_name ?? 'captain'}
                  </span>
                )}
              </div>
              <textarea
                className="input w-full min-h-[80px] resize-y text-sm"
                placeholder="Structured operational note for this building…"
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                maxLength={2000}
              />
              <div className="flex gap-2">
                <button
                  onClick={handleSaveNote}
                  disabled={savingNote || noteText === (profile.operational_note ?? '')}
                  className="btn-ghost text-xs px-3 py-1.5"
                >
                  {savingNote ? 'Saving…' : 'Save Note'}
                </button>
                {profile.operational_note && !profile.note_verified && (
                  <button
                    onClick={handleVerifyNote}
                    disabled={verifyingNote}
                    className="btn-primary text-xs px-3 py-1.5"
                  >
                    {verifyingNote ? 'Verifying…' : 'Verify Note'}
                  </button>
                )}
              </div>
            </div>
          )}
          {!canVerify && profile.operational_note && (
            <div className="space-y-1">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                Operational Note
                {profile.note_verified && <CheckCircle2 className="w-3.5 h-3.5 text-success" />}
              </p>
              <p className="text-sm text-foreground bg-accent/40 rounded-xl p-3 whitespace-pre-wrap">{profile.operational_note}</p>
            </div>
          )}

          {/* Verify building type */}
          {canVerify && profile.building_type_status !== 'locked' && (
            <div className="space-y-2 border-t border-border pt-4">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Verify Building Type</p>
              <p className="text-xs text-muted-foreground">Confirm or correct this building's type. Each agreement moves it toward locked.</p>
              <select
                className="input w-full"
                value={verifyType}
                onChange={e => setVerifyType(e.target.value)}
              >
                {BUILDING_TYPES.map(b => (
                  <option key={b.value} value={b.value}>{b.label}</option>
                ))}
              </select>
              <button
                onClick={handleVerify}
                disabled={verifying}
                className="btn-primary w-full text-sm"
              >
                {verifying ? 'Verifying…' : verifyType === profile.building_type ? 'Confirm' : 'Correct & Verify'}
              </button>
            </div>
          )}

          {profile.building_type_status === 'locked' && (
            <div className="flex items-center gap-2 p-3 rounded-xl bg-success/10 border border-success/20 text-xs text-success">
              <Lock className="w-3.5 h-3.5 shrink-0" />
              <span>This profile is locked and active for routing. Verified by {profile.verified_by_name ?? 'captain'} on {fmt(profile.verified_at)}.</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function LocationProfiles() {
  const { groups } = useAuth();
  const canVerify = groups.some(g => ['dispatch', 'management', 'admin'].includes(g));

  const [profiles, setProfiles] = useState<LocationProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showSubmit, setShowSubmit] = useState(false);
  const [selected, setSelected] = useState<LocationProfile | null>(null);

  const fetchProfiles = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params: Record<string, string> = { limit: '200' };
      if (statusFilter) params.status = statusFilter;
      const res = await axiosClient.get<LocationProfile[]>('/location-profiles/', { params });
      setProfiles(res.data);
    } catch {
      setError('Failed to load location profiles.');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { fetchProfiles(); }, [fetchProfiles]);

  const handleUpdate = (updated: LocationProfile) => {
    setProfiles(prev => prev.map(p => p.id === updated.id ? updated : p));
    setSelected(updated);
  };

  const filtered = profiles.filter(p =>
    !search ||
    p.block_key.toLowerCase().includes(search.toLowerCase()) ||
    p.building_type.toLowerCase().includes(search.toLowerCase())
  );

  const locked   = filtered.filter(p => p.building_type_status === 'locked');
  const verified = filtered.filter(p => p.building_type_status === 'verified');
  const pending  = filtered.filter(p => p.building_type_status === 'pending');

  return (
    <div className="space-y-6 animate-slide-up">
      <SectionHeader
        title="Location Profiles"
        subtitle="Crowdsourced building intelligence for delivery routing"
        icon={Building2}
        action={
          <button onClick={() => setShowSubmit(true)} className="btn-primary flex items-center gap-1.5 text-sm">
            <Plus className="w-3.5 h-3.5" /> Submit Profile
          </button>
        }
      />

      {error && <ErrorBanner message={error} />}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            className="input pl-8 w-full text-sm"
            placeholder="Search block key or type…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <select
          className="input text-sm"
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="locked">Locked</option>
          <option value="verified">Verified</option>
          <option value="pending">Pending</option>
        </select>
        <button onClick={fetchProfiles} className="btn-ghost p-2" title="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Locked',   count: locked.length,   cls: 'text-success',  bg: 'bg-success/10'  },
          { label: 'Verified', count: verified.length,  cls: 'text-info',     bg: 'bg-info/10'     },
          { label: 'Pending',  count: pending.length,   cls: 'text-muted-foreground', bg: 'bg-accent' },
        ].map(s => (
          <div key={s.label} className={`card flex flex-col items-center py-3 ${s.bg} border-0`}>
            <p className={`text-xl font-bold ${s.cls}`}>{s.count}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Profile list */}
      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="card text-center py-12">
          <FileText className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">No profiles found.</p>
          <button onClick={() => setShowSubmit(true)} className="btn-primary mt-4 text-sm">
            Submit the first profile
          </button>
        </div>
      ) : (
        <div className="space-y-1">
          {[...locked, ...verified, ...pending].map(profile => (
            <button
              key={profile.id}
              onClick={() => setSelected(profile)}
              className="w-full card hover:border-border-strong transition-colors text-left flex items-center gap-3 py-3 px-4"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-sm font-semibold text-foreground truncate">{profile.block_key}</span>
                  <span className="text-xs text-muted-foreground">{buildingLabel(profile.building_type)}</span>
                </div>
                <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                  <StatusBadge status={profile.building_type_status} />
                  <WorkloadBadge workload={profile.workload_class} />
                  {profile.operational_note && (
                    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                      <FileText className="w-3 h-3" />
                      {profile.note_verified ? 'Note verified' : 'Note pending'}
                    </span>
                  )}
                </div>
              </div>
              <div className="text-xs text-muted-foreground shrink-0 text-right">
                <p>{profile.building_type_agreement_count} agreement{profile.building_type_agreement_count !== 1 ? 's' : ''}</p>
                <p className="mt-0.5">{fmt(profile.updated_at)}</p>
              </div>
            </button>
          ))}
        </div>
      )}

      {showSubmit && (
        <SubmitModal onClose={() => setShowSubmit(false)} onSubmitted={fetchProfiles} />
      )}
      {selected && (
        <ProfilePanel
          profile={selected}
          canVerify={canVerify}
          onUpdate={handleUpdate}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
