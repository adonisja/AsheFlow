import { errorText } from '../utils/errorText';
import React, { useState, useEffect, useCallback } from 'react';
import {
  Users, Truck, Plus, Pencil, CheckCircle2, AlertTriangle,
  RefreshCw, X, ChevronDown, Settings, Trash2, FileUp, Mail, ArrowUp, ArrowDown,
  Copy, Check, Hash, Search, ToggleLeft, ToggleRight, ShieldAlert, ShieldOff, Phone,
  MapPin, Loader2, Map, MousePointer2, Navigation,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import type { CompanyZone, CornerPoint } from '../api/types';
import { useAuth } from '../contexts/AuthContext';
import BulkImportModal from '../components/BulkImportModal';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import CompanyZoneMap from '../components/OperatingZoneMap';
import { useConfirm } from '../hooks/useConfirm';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Employee = {
  id: string;
  name: string;
  email: string | null;
  discord_id: string | null;
  cognito_sub: string | null;
  username: string | null;
  role: string;
  is_active: boolean;
  account_status: string;
  phone_number: string | null;
  invited_at: string | null;
  injury_status: 'injured' | 'disabled' | null;
  injury_status_since: string | null;
};

type EmployeeLifecycle = 'not_invited' | 'invited' | 'registered' | 'active' | 'deactivated';

function getLifecycle(e: Employee): EmployeeLifecycle {
  if (e.account_status === 'active' && !e.is_active) return 'deactivated';
  if (e.account_status === 'active'  &&  e.is_active) return 'active';
  // pending_verification below
  if (e.username) return 'registered';   // form submitted, Cognito account exists, not signed in yet
  if (e.invited_at) return 'invited';    // invite email sent, link not yet used
  return 'not_invited';                  // record created, invite never sent
}

const LIFECYCLE_BADGE: Record<EmployeeLifecycle, { label: string; cls: string }> = {
  not_invited: { label: 'Not invited',  cls: 'bg-accent text-muted-foreground' },
  invited:     { label: 'Invited',      cls: 'bg-warning/10 text-warning' },
  registered:  { label: 'Registered',   cls: 'bg-info/10 text-info' },
  active:      { label: 'Active',       cls: 'bg-success/10 text-success' },
  deactivated: { label: 'Deactivated',  cls: 'bg-danger/10 text-danger' },
};

type TruckRecord = {
  id: string;
  name: string;
  is_active: boolean;
  discord_channel_id: string | null;
  initial_anchor_address: string | null;
  initial_anchor_display_address: string | null;
  initial_anchor_lat: number | null;
  initial_anchor_lng: number | null;
  initial_anchor_set_at: string | null;
  initial_anchor2_address: string | null;
  initial_anchor2_display_address: string | null;
  initial_anchor2_lat: number | null;
  initial_anchor2_lng: number | null;
  initial_anchor2_set_at: string | null;
};

type Tab = 'people' | 'fleet' | 'system';

const ROLES = ['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin'];
// Roles that can be directly assigned at creation time — walker and trainer are earned, not assigned
const CREATABLE_ROLES = ['driver', 'trainee', 'dispatch', 'management', 'admin'];
// Management callers are further restricted to field-entry roles only
const MANAGEMENT_CREATABLE_ROLES = ['driver', 'trainee'];
const PROTECTED_ROLES = ['management', 'admin'];

const ROLE_CREATION_NOTICES: Partial<Record<string, string>> = {
  walker:  'Walkers must start as trainees and be assigned the walker role by dispatch.',
  trainer: 'Trainers can only be promoted from existing walkers by a manager or admin.',
};

// Formats the 10-digit local portion as (xxx) xxx-xxxx as the user types.
// The +1 country code is rendered as a static prefix outside the input.
function formatUSPhone(raw: string): string {
  // Strip everything except digits, cap at 10
  const digits = raw.replace(/\D/g, '').slice(0, 10);
  if (digits.length === 0)  return '';
  if (digits.length <= 3)   return `(${digits}`;
  if (digits.length <= 6)   return `(${digits.slice(0, 3)}) ${digits.slice(3)}`;
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

function isValidUSPhone(raw: string): boolean {
  return raw.replace(/\D/g, '').length === 10;
}

// Storage format for the DB — always +1xxxxxxxxxx
function toE164Phone(formatted: string): string {
  const digits = formatted.replace(/\D/g, '');
  return digits.length === 10 ? `+1${digits}` : formatted;
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

const ROLE_COLORS: Record<string, string> = {
  driver:     'bg-blue-500/10 text-blue-500',
  walker:     'bg-emerald-500/10 text-emerald-600',
  trainer:    'bg-purple-500/10 text-purple-600',
  trainee:    'bg-amber-500/10 text-amber-600',
  dispatch:   'bg-indigo-500/10 text-indigo-600',
  management: 'bg-teal-500/10 text-teal-600',
  admin:      'bg-rose-500/10 text-rose-600',
};

const ROLE_AVATAR_COLORS: Record<string, string> = {
  driver:     'bg-blue-100 text-blue-700',
  walker:     'bg-emerald-100 text-emerald-700',
  trainer:    'bg-purple-100 text-purple-700',
  trainee:    'bg-amber-100 text-amber-700',
  dispatch:   'bg-indigo-100 text-indigo-700',
  management: 'bg-teal-100 text-teal-700',
  admin:      'bg-rose-100 text-rose-700',
};

function badge(role: string) {
  return `inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${ROLE_COLORS[role] ?? 'bg-accent text-foreground'}`;
}

function RoleAvatar({ name, role }: { name: string; role: string }) {
  const initials = name.trim().split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
  const cls = ROLE_AVATAR_COLORS[role] ?? 'bg-accent text-muted-foreground';
  return (
    <div className={`shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ${cls}`}>
      {initials}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Employee modals
// ---------------------------------------------------------------------------

type EmployeeFormProps = {
  initial?: Partial<Employee>;
  onSave: (data: Record<string, string>) => Promise<void>;
  onClose: () => void;
  isCreate: boolean;
  allowedRoles?: string[];
};

function EmployeeModal({ initial = {}, onSave, onClose, isCreate, allowedRoles = ROLES }: EmployeeFormProps) {
  const defaultRole = allowedRoles.includes('driver') ? 'driver' : allowedRoles[0] ?? 'driver';
  const [form, setForm] = useState({
    name:         initial.name         ?? '',
    email:        initial.email        ?? '',
    discord_id:   initial.discord_id   ?? '',
    role:         initial.role         ?? defaultRole,
    phone_number: initial.phone_number ?? '',
  });
  const [step,        setStep]        = useState<'form' | 'review'>('form');
  const [saving,      setSaving]      = useState(false);
  const [error,       setError]       = useState('');
  const [phoneError,  setPhoneError]  = useState('');
  const [discordError, setDiscordError] = useState('');

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  const handleDiscordChange = (v: string) => {
    set('discord_id', v);
    if (v && !/^\d{17,20}$/.test(v.trim())) {
      setDiscordError('Must be a numeric snowflake ID (17-20 digits)');
    } else {
      setDiscordError('');
    }
  };

  const handlePhoneChange = (v: string) => {
    set('phone_number', formatUSPhone(v));
    setPhoneError('');
  };

  const handleFormNext = (e: React.FormEvent) => {
    e.preventDefault();
    if (form.phone_number && !isValidUSPhone(form.phone_number)) {
      setPhoneError('Enter a valid 10-digit US phone number.');
      return;
    }
    if (form.discord_id.trim() && !/^\d{17,20}$/.test(form.discord_id.trim())) {
      setDiscordError('Must be a numeric snowflake ID (17-20 digits)');
      return;
    }
    if (isCreate) { setStep('review'); return; }
    handleSave();
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await onSave({
        ...form,
        phone_number: form.phone_number ? toE164Phone(form.phone_number) : '',
      });
    } catch (err: any) {
      setError(errorText(err, 'Something went wrong.'));
      setStep('form');
    } finally {
      setSaving(false);
    }
  };

  const roleNotice = isCreate ? ROLE_CREATION_NOTICES[form.role] : undefined;
  const roleLabel  = form.role.charAt(0).toUpperCase() + form.role.slice(1);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-card w-full max-w-md rounded-2xl border border-border shadow-xl animate-slide-up">
        {/* Header */}
        <div className="px-6 py-4 border-b border-border bg-primary/[0.03]">
          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-base font-semibold text-foreground">
                {isCreate ? (step === 'review' ? 'Confirm Invite' : 'Invite New Employee') : 'Edit Employee'}
              </h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                {isCreate
                  ? (step === 'review' ? 'Review the details below before sending.' : "They'll receive an email with a registration link.")
                  : "Update this employee's details."}
              </p>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground transition-colors -mt-0.5">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* ── STEP 1: Form ── */}
        {step === 'form' && (
          <form onSubmit={handleFormNext} className="p-6 space-y-5">
            {error && (
              <div className="flex items-start gap-2 text-sm text-danger bg-danger/10 border border-danger/20 rounded-xl px-3 py-2.5">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                {error}
              </div>
            )}

            {/* Name */}
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-foreground">
                Full name <span className="text-danger">*</span>
              </label>
              <div className="flex items-stretch rounded-xl border border-border bg-input overflow-hidden focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all">
                <input
                  required
                  value={form.name}
                  onChange={e => set('name', e.target.value)}
                  className="flex-1 px-3 py-2.5 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
                  placeholder="Jane Smith"
                />
              </div>
            </div>

            {/* Email */}
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-foreground">
                Email {isCreate && <span className="text-danger">*</span>}
              </label>
              <div className="flex items-stretch rounded-xl border border-border bg-input overflow-hidden focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all">
                <input
                  required={isCreate}
                  type="email"
                  value={form.email}
                  onChange={e => set('email', e.target.value)}
                  className="flex-1 px-3 py-2.5 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
                  placeholder="jane@example.com"
                />
              </div>
              {isCreate && (
                <p className="text-xs text-muted-foreground">A registration link will be sent to this address.</p>
              )}
            </div>

            {/* Discord ID (edit only) */}
            {!isCreate && (
              <div className="space-y-1.5">
                <label className="block text-sm font-medium text-foreground">Discord ID</label>
                <div className="flex items-stretch rounded-xl border border-border bg-input overflow-hidden focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all">
                  <input
                    value={form.discord_id}
                    onChange={e => handleDiscordChange(e.target.value)}
                    className="flex-1 px-3 py-2.5 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
                    placeholder="Numeric snowflake (e.g. 123456789012345678)"
                  />
                </div>
                {discordError && <p className="text-xs text-danger mt-1">{discordError}</p>}
                {!form.discord_id && <p className="text-xs text-muted-foreground mt-1">Leave blank if unknown — employee can link via registration.</p>}
              </div>
            )}

            {/* Role */}
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-foreground">
                Role <span className="text-danger">*</span>
              </label>
              <div className="flex items-stretch rounded-xl border border-border bg-input overflow-hidden focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all">
                <select
                  required
                  value={form.role}
                  onChange={e => set('role', e.target.value)}
                  className="flex-1 px-3 py-2.5 bg-transparent text-sm text-foreground appearance-none focus:outline-none pr-8"
                >
                  {allowedRoles.map(r => (
                    <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>
                  ))}
                </select>
                <span className="flex items-center pr-3 text-muted-foreground pointer-events-none shrink-0">
                  <ChevronDown className="w-4 h-4" />
                </span>
              </div>
              {roleNotice && (
                <p className="text-xs text-warning bg-warning/10 border border-warning/20 rounded-lg px-2.5 py-1.5">
                  {roleNotice}
                </p>
              )}
            </div>

            {/* Phone */}
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-foreground">
                Phone <span className="text-xs font-normal text-muted-foreground">(optional)</span>
              </label>
              <div className={`flex items-stretch rounded-xl border bg-input overflow-hidden focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all ${phoneError ? 'border-danger/60' : 'border-border'}`}>
                <span className="flex items-center px-3 text-sm font-semibold text-muted-foreground bg-accent/60 border-r border-border select-none shrink-0">
                  +1
                </span>
                <input
                  type="tel"
                  value={form.phone_number}
                  onChange={e => handlePhoneChange(e.target.value)}
                  className="flex-1 px-3 py-2.5 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
                  placeholder="(555) 000-0000"
                />
              </div>
              {phoneError && <p className="text-xs text-danger">{phoneError}</p>}
            </div>

            <div className="flex justify-end gap-3 pt-1">
              <button type="button" onClick={onClose} className="btn-ghost px-4">Cancel</button>
              <button type="submit" className="btn-primary flex items-center gap-2 px-5">
                {isCreate ? 'Review Invite' : 'Save Changes'}
              </button>
            </div>
          </form>
        )}

        {/* ── STEP 2: Review (create only) ── */}
        {step === 'review' && (
          <div className="p-6 space-y-5">
            {error && (
              <div className="flex items-start gap-2 text-sm text-danger bg-danger/10 border border-danger/20 rounded-xl px-3 py-2.5">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                {error}
              </div>
            )}

            {/* Summary card */}
            <div className="rounded-xl border border-border overflow-hidden">
              <div className="px-4 py-2.5 bg-accent/40 border-b border-border">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Invite summary</p>
              </div>
              <div className="divide-y divide-border">
                {[
                  { label: 'Name',  value: form.name },
                  { label: 'Email', value: form.email },
                  { label: 'Role',  value: roleLabel },
                  ...(form.phone_number ? [{ label: 'Phone', value: `+1 ${form.phone_number}` }] : []),
                ].map(({ label, value }) => (
                  <div key={label} className="flex items-center justify-between px-4 py-3">
                    <span className="text-xs text-muted-foreground">{label}</span>
                    <span className="text-sm font-medium text-foreground">{value}</span>
                  </div>
                ))}
              </div>
            </div>

            <p className="text-xs text-muted-foreground text-center">
              A registration link will be sent to <span className="font-medium text-foreground">{form.email}</span>.
            </p>

            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setStep('form')}
                disabled={saving}
                className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-xl border border-border text-sm font-medium text-foreground hover:bg-accent transition-colors disabled:opacity-50"
              >
                <Pencil className="w-3.5 h-3.5" /> Edit
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={saving}
                className="flex-1 btn-primary py-2.5 flex items-center justify-center gap-2"
              >
                {saving && <div className="w-3.5 h-3.5 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />}
                {saving ? 'Sending…' : 'Send Invite'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Truck modal
// ---------------------------------------------------------------------------

type TruckModalProps = {
  initial?: Partial<TruckRecord>;
  onSave: (data: { name: string; discord_channel_id: string | null }) => Promise<void>;
  onClose: () => void;
  isCreate: boolean;
};

function TruckModal({ initial = {}, onSave, onClose, isCreate }: TruckModalProps) {
  const [name, setName]           = useState(initial.name ?? '');
  const [channelId, setChannelId] = useState(
    initial.discord_channel_id ? String(initial.discord_channel_id) : ''
  );
  const [saving, setSaving]       = useState(false);
  const [error, setError]         = useState('');

  const channelIdValid = channelId === '' || /^\d{17,20}$/.test(channelId.trim());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!channelIdValid) return;
    setSaving(true);
    setError('');
    try {
      await onSave({
        name,
        // Send as string — Discord snowflake IDs exceed Number.MAX_SAFE_INTEGER.
        // Backend TruckUpdate accepts Optional[int] and Pydantic coerces string → int.
        discord_channel_id: channelId.trim() || null,
      });
    } catch (err: any) {
      setError(errorText(err, 'Something went wrong.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-card w-full max-w-md rounded-2xl border border-border shadow-xl animate-slide-up">
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
              <Truck className="w-4 h-4 text-primary" />
            </div>
            <h2 className="font-semibold text-foreground">{isCreate ? 'Add Truck' : 'Edit Truck'}</h2>
          </div>
          <button onClick={onClose} className="btn-ghost p-1.5"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-5">
          {error && (
            <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-xl px-3 py-2">
              {error}
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Truck Name <span className="text-danger">*</span>
            </label>
            <input
              required
              value={name}
              onChange={e => setName(e.target.value)}
              className="input w-full"
              placeholder="e.g. Atlas"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Discord Channel ID
            </label>
            <input
              value={channelId}
              onChange={e => setChannelId(e.target.value)}
              className={`input w-full font-mono text-sm ${!channelIdValid ? 'border-danger/60 focus:ring-danger/30' : ''}`}
              placeholder="e.g. 1234567890123456789"
            />
            {!channelIdValid ? (
              <p className="text-xs text-danger flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" /> Must be a valid Discord snowflake (17–20 digits).
              </p>
            ) : channelId ? (
              <p className="text-xs text-success flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Channel will be linked
              </p>
            ) : (
              <p className="text-xs text-muted-foreground">
                Right-click a channel in Discord → <strong>Copy Channel ID</strong>.{' '}
                {!isCreate && 'Leave blank to unlink.'}
              </p>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-1">
            <button type="button" onClick={onClose} className="btn-ghost px-4">Cancel</button>
            <button
              type="submit"
              disabled={saving || !channelIdValid}
              className="btn-primary flex items-center gap-2 px-5"
            >
              {saving && <div className="w-3.5 h-3.5 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />}
              {isCreate ? 'Add Truck' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// People Tab
// ---------------------------------------------------------------------------

const PEOPLE_PAGE_SIZE = 25;

function PeopleTab() {
  const { groups }                    = useAuth();
  const isAdmin                       = groups.includes('admin');
  const isManagement                  = groups.includes('management') && !isAdmin;
  const canImport                     = groups.includes('management') || isAdmin;
  const allowedRoles                  = isManagement ? MANAGEMENT_CREATABLE_ROLES : CREATABLE_ROLES;
  const { confirmState, confirm, cancelConfirm } = useConfirm();

  const [employees, setEmployees]     = useState<Employee[]>([]);
  const [loading, setLoading]         = useState(true);
  const [loadError, setLoadError]     = useState<string | null>(null);
  const [showModal, setShowModal]     = useState(false);
  const [showImport, setShowImport]   = useState(false);
  const [editTarget, setEditTarget]   = useState<Employee | null>(null);
  const [filter, setFilter]           = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'pending' | 'deactivated'>('all');
  const [search, setSearch]           = useState('');
  const [page, setPage]               = useState(0);
  const [resendingId, setResendingId]     = useState<string | null>(null);
  const [resendMsg, setResendMsg]         = useState<{ id: string; ok: boolean; text: string } | null>(null);
  const [promotingId, setPromotingId]     = useState<string | null>(null);
  const [promoteMsg, setPromoteMsg]       = useState<{ id: string; ok: boolean; text: string } | null>(null);

  const load = () => {
    setLoading(true);
    setLoadError(null);
    axiosClient.get('/employees/?limit=500&include_inactive=true')
      .then(r => setEmployees(r.data))
      .catch(() => setLoadError('Failed to load employees. Check your connection and try again.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (data: Record<string, string>) => {
    const payload: Record<string, string | null> = { ...data };
    if (!payload.phone_number) payload.phone_number = null;
    const res = await axiosClient.post('/employees/', payload);
    setEmployees(prev => [...prev, res.data]);
    setShowModal(false);
  };

  const handleEdit = async (data: Record<string, string>) => {
    if (!editTarget) return;
    const payload: Record<string, string | null> = { ...data };
    if (!payload.phone_number) payload.phone_number = null;
    const res = await axiosClient.put(`/employees/${editTarget.id}`, payload);
    setEmployees(prev => prev.map(e => e.id === editTarget.id ? res.data : e));
    setEditTarget(null);
  };

  const handleResendInvite = async (emp: Employee) => {
    setResendingId(emp.id);
    setResendMsg(null);
    try {
      await axiosClient.post('/registration/invite', { employee_id: emp.id });
      setResendMsg({ id: emp.id, ok: true, text: `Invite re-sent to ${emp.email}.` });
    } catch (err: any) {
      setResendMsg({ id: emp.id, ok: false, text: errorText(err, 'Failed to send invite.') });
    } finally {
      setResendingId(null);
    }
  };

  const handleResendCredentials = async (emp: Employee) => {
    setResendingId(emp.id);
    setResendMsg(null);
    try {
      await axiosClient.post('/registration/resend-credentials', { employee_id: emp.id });
      setResendMsg({ id: emp.id, ok: true, text: `Credentials re-sent to ${emp.email}.` });
    } catch (err: any) {
      setResendMsg({ id: emp.id, ok: false, text: errorText(err, 'Failed to resend credentials.') });
    } finally {
      setResendingId(null);
    }
  };

  const handleToggleActive = async (emp: Employee) => {
    const action = emp.is_active ? 'deactivate' : 'reactivate';
    const ok = await confirm({
      title: `${action.charAt(0).toUpperCase() + action.slice(1)} Employee`,
      message: `${action.charAt(0).toUpperCase() + action.slice(1)} ${emp.name}? ${emp.is_active ? 'They will lose system access.' : 'They will regain system access.'}`,
      confirmLabel: action.charAt(0).toUpperCase() + action.slice(1),
      variant: emp.is_active ? 'danger' : 'default',
    });
    if (!ok) return;
    const res = await axiosClient.put(`/employees/${emp.id}/${action}`);
    setEmployees(prev => prev.map(e => e.id === emp.id ? res.data : e));
  };

  const handlePromote = async (emp: Employee) => {
    const ok = await confirm({
      title: 'Promote to Trainer',
      message: `Promote ${emp.name} from walker to trainer? They will gain trainer permissions on their next login.`,
      confirmLabel: 'Promote',
      variant: 'default',
    });
    if (!ok) return;
    setPromotingId(emp.id);
    setPromoteMsg(null);
    try {
      const res = await axiosClient.post(`/employees/${emp.id}/promote`);
      setEmployees(prev => prev.map(e => e.id === emp.id ? res.data : e));
      setPromoteMsg({ id: emp.id, ok: true, text: `${emp.name} promoted to trainer.` });
    } catch (err: any) {
      setPromoteMsg({ id: emp.id, ok: false, text: errorText(err, 'Promotion failed.') });
    } finally {
      setPromotingId(null);
    }
  };

  const handleDemote = async (emp: Employee) => {
    const ok = await confirm({
      title: 'Demote to Walker',
      message: `Demote ${emp.name} from trainer to walker? They will lose trainer permissions on their next login.`,
      confirmLabel: 'Demote',
      variant: 'danger',
    });
    if (!ok) return;
    setPromotingId(emp.id);
    setPromoteMsg(null);
    try {
      const res = await axiosClient.post(`/employees/${emp.id}/demote`);
      setEmployees(prev => prev.map(e => e.id === emp.id ? res.data : e));
      setPromoteMsg({ id: emp.id, ok: true, text: `${emp.name} demoted to walker.` });
    } catch (err: any) {
      setPromoteMsg({ id: emp.id, ok: false, text: errorText(err, 'Demotion failed.') });
    } finally {
      setPromotingId(null);
    }
  };

  const handleDelete = async (emp: Employee) => {
    const ok = await confirm({
      title: 'Delete Employee',
      message: `Permanently delete ${emp.name}? This revokes their access immediately and cannot be undone.`,
      confirmLabel: 'Delete',
      variant: 'danger',
    });
    if (!ok) return;
    await axiosClient.delete(`/employees/${emp.id}`);
    setEmployees(prev => prev.filter(e => e.id !== emp.id));
  };

  const visible = employees.filter(e => {
    // Management callers never see management/admin rows
    if (isManagement && PROTECTED_ROLES.includes(e.role)) return false;
    const matchRole   = filter === 'all' || e.role === filter;
    const matchSearch = !search || e.name.toLowerCase().includes(search.toLowerCase())
      || (e.email ?? '').toLowerCase().includes(search.toLowerCase())
      || (e.discord_id ?? '').toLowerCase().includes(search.toLowerCase());
    const lc = getLifecycle(e);
    const matchStatus = statusFilter === 'all'
      || (statusFilter === 'pending' && (lc === 'not_invited' || lc === 'invited' || lc === 'registered'))
      || (statusFilter === 'active' && lc === 'active')
      || (statusFilter === 'deactivated' && lc === 'deactivated');
    return matchRole && matchSearch && matchStatus;
  });

  const totalPages  = Math.ceil(visible.length / PEOPLE_PAGE_SIZE);
  const currentPage = Math.min(page, Math.max(0, totalPages - 1));
  const pageSlice   = visible.slice(currentPage * PEOPLE_PAGE_SIZE, (currentPage + 1) * PEOPLE_PAGE_SIZE);

  const injuredCount  = employees.filter(e => e.injury_status === 'injured').length;
  const disabledCount = employees.filter(e => e.injury_status === 'disabled').length;
  const activeCount   = employees.filter(e => e.account_status === 'active' && e.is_active).length;
  const pendingCount  = employees.filter(e => e.account_status === 'pending_verification').length;
  const deactivatedCount = employees.filter(e => e.account_status === 'active' && !e.is_active).length;

  return (
    <div className="space-y-5">
      <ConfirmDialog {...confirmState} onCancel={cancelConfirm} />

      {/* KPI summary */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        {[
          { label: 'Active',      value: activeCount,      color: 'text-success',          filterVal: 'active'      as typeof statusFilter },
          { label: 'Pending',     value: pendingCount,     color: 'text-warning',          filterVal: 'pending'     as typeof statusFilter },
          { label: 'Deactivated', value: deactivatedCount, color: 'text-muted-foreground', filterVal: 'deactivated' as typeof statusFilter },
          { label: 'Injured',     value: injuredCount,     color: 'text-orange-500',       filterVal: null },
          { label: 'Disabled',    value: disabledCount,    color: 'text-danger',           filterVal: null },
        ].map(({ label, value, color, filterVal }) => (
          <button
            key={label}
            onClick={() => {
              if (!filterVal) return;
              setStatusFilter(prev => prev === filterVal ? 'all' : filterVal);
              setPage(0);
            }}
            className={`card text-center py-3 transition-colors ${filterVal ? 'hover:bg-accent/50 cursor-pointer' : 'cursor-default'} ${statusFilter === filterVal && filterVal ? 'ring-2 ring-primary/30' : ''}`}
          >
            <p className={`text-2xl font-bold ${color}`}>{value}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
          </button>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            type="search"
            placeholder="Search name, email, Discord…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(0); }}
            className="input pl-8 w-full"
          />
        </div>
        <div className="relative">
          <select
            value={filter}
            onChange={e => { setFilter(e.target.value); setPage(0); }}
            className="input pr-8 appearance-none capitalize"
          >
            <option value="all">All roles</option>
            {ROLES.map(r => <option key={r} value={r} className="capitalize">{r}</option>)}
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
        </div>
        <div className="relative">
          <select
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value as typeof statusFilter); setPage(0); }}
            className="input pr-8 appearance-none"
          >
            <option value="all">All Statuses</option>
            <option value="pending">Pending</option>
            <option value="active">Active</option>
            <option value="deactivated">Deactivated</option>
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
        </div>
        <button onClick={load} className="btn-ghost text-muted-foreground p-2" title="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
        {canImport && (
          <button
            onClick={() => setShowImport(true)}
            className="btn-ghost flex items-center gap-2 text-sm ml-auto"
          >
            <FileUp className="w-4 h-4" /> Import
          </button>
        )}
        <button
          onClick={() => setShowModal(true)}
          className={`btn-primary flex items-center gap-2 ${canImport ? '' : 'ml-auto'}`}
        >
          <Plus className="w-4 h-4" /> Invite Employee
        </button>
      </div>

      {visible.length !== employees.length && (
        <p className="text-xs text-subtle">{visible.length} of {employees.length} shown</p>
      )}

      {/* Table */}
      {loadError && (
        <div className="card border-danger/30 bg-danger/5 text-danger text-sm px-4 py-3 rounded-xl flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" /> {loadError}
        </div>
      )}
      {loading ? (
        <div className="space-y-2">
          {[0,1,2,3,4,5].map(i => (
            <div key={i} className="card h-12 animate-pulse bg-accent/40" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="card text-center py-16 space-y-2">
          <Users className="w-8 h-8 text-muted-foreground mx-auto" />
          <p className="text-muted-foreground text-sm">No employees found.</p>
        </div>
      ) : (
        <div className="card overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border bg-accent/30">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Role</th>
                  <th className="px-4 py-3 hidden sm:table-cell">Email</th>
                  <th className="px-4 py-3 hidden md:table-cell">Discord</th>
                  <th className="px-4 py-3 hidden lg:table-cell">Phone</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {pageSlice.map(emp => {
                  const lc = getLifecycle(emp);
                  const { label, cls } = LIFECYCLE_BADGE[lc];
                  return (
                    <tr key={emp.id} className={`transition-colors hover:bg-accent/20 ${lc === 'deactivated' ? 'opacity-50' : ''}`}>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="flex items-center gap-2.5">
                          <RoleAvatar name={emp.name} role={emp.role} />
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              <span className="font-medium text-foreground text-sm">{emp.name}</span>
                              {emp.injury_status === 'injured' && (
                                <span
                                  title={`Injured${emp.injury_status_since ? ` since ${new Date(emp.injury_status_since).toLocaleDateString()}` : ''}`}
                                  className="inline-flex items-center gap-1 text-[10px] font-semibold bg-orange-500/10 text-orange-500 border border-orange-500/20 px-1.5 py-0.5 rounded-full"
                                >
                                  <ShieldAlert className="w-2.5 h-2.5" /> Injured
                                </span>
                              )}
                              {emp.injury_status === 'disabled' && (
                                <span
                                  title={`Disabled${emp.injury_status_since ? ` since ${new Date(emp.injury_status_since).toLocaleDateString()}` : ''}`}
                                  className="inline-flex items-center gap-1 text-[10px] font-semibold bg-danger/10 text-danger border border-danger/20 px-1.5 py-0.5 rounded-full"
                                >
                                  <ShieldOff className="w-2.5 h-2.5" /> Disabled
                                </span>
                              )}
                            </div>
                            {emp.username && (
                              <span className="text-[11px] text-muted-foreground font-mono">{emp.username}</span>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className={badge(emp.role)}>{emp.role}</span>
                      </td>
                      <td className="px-4 py-3 hidden sm:table-cell text-muted-foreground text-xs truncate max-w-[180px]">
                        {emp.email ?? <span className="text-subtle italic">—</span>}
                      </td>
                      <td className="px-4 py-3 hidden md:table-cell">
                        {emp.discord_id
                          ? <CopyableId value={emp.discord_id} />
                          : <span className="text-xs text-warning italic">not set</span>}
                      </td>
                      <td className="px-4 py-3 hidden lg:table-cell">
                        {emp.phone_number
                          ? (
                            <button
                              onClick={() => navigator.clipboard.writeText(emp.phone_number!)}
                              className="group flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                              title="Copy phone number"
                            >
                              <Phone className="w-3 h-3 shrink-0" />
                              <span>{emp.phone_number}</span>
                              <Copy className="w-3 h-3 shrink-0 opacity-0 group-hover:opacity-50 transition-opacity" />
                            </button>
                          )
                          : <span className="text-subtle italic text-xs">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
                          {label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        <div className="inline-flex items-center gap-2">
                          {promoteMsg?.id === emp.id && (
                            <span
                              className={`text-xs font-medium max-w-[160px] truncate ${promoteMsg.ok ? 'text-success' : 'text-danger'}`}
                              title={promoteMsg.text}
                            >
                              {promoteMsg.ok ? 'Done' : 'Failed'}
                            </span>
                          )}
                          {resendMsg?.id === emp.id && (
                            <span
                              className={`text-xs font-medium max-w-[160px] truncate ${resendMsg.ok ? 'text-success' : 'text-danger'}`}
                              title={resendMsg.text}
                            >
                              {resendMsg.ok ? 'Invite sent' : 'Failed'}
                            </span>
                          )}
                          {(lc === 'not_invited' || lc === 'invited') && emp.email && (
                            <button
                              onClick={() => handleResendInvite(emp)}
                              disabled={resendingId === emp.id}
                              className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:bg-primary/10 px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                              title="Re-send registration invite email"
                            >
                              {resendingId === emp.id
                                ? <div className="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                                : <Mail className="w-3 h-3" />}
                              {lc === 'not_invited' ? 'Send Invite' : 'Resend Invite'}
                            </button>
                          )}
                          {lc === 'registered' && emp.email && (
                            <button
                              onClick={() => handleResendCredentials(emp)}
                              disabled={resendingId === emp.id}
                              className="inline-flex items-center gap-1 text-xs font-medium text-info hover:bg-info/10 px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                              title="Re-send credentials email (username + temp password)"
                            >
                              {resendingId === emp.id
                                ? <div className="w-3 h-3 border-2 border-info border-t-transparent rounded-full animate-spin" />
                                : <Mail className="w-3 h-3" />}
                              Resend Credentials
                            </button>
                          )}
                          {emp.role === 'walker' && emp.account_status === 'active' && (
                            <button
                              onClick={() => handlePromote(emp)}
                              disabled={promotingId === emp.id}
                              className="inline-flex items-center gap-1 text-xs font-medium text-violet hover:bg-violet/10 px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                              title="Promote to trainer"
                            >
                              {promotingId === emp.id
                                ? <div className="w-3 h-3 border-2 border-violet border-t-transparent rounded-full animate-spin" />
                                : <ArrowUp className="w-3 h-3" />}
                              Promote
                            </button>
                          )}
                          {emp.role === 'trainer' && emp.account_status === 'active' && (
                            <button
                              onClick={() => handleDemote(emp)}
                              disabled={promotingId === emp.id}
                              className="inline-flex items-center gap-1 text-xs font-medium text-warning hover:bg-warning/10 px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                              title="Demote to walker"
                            >
                              {promotingId === emp.id
                                ? <div className="w-3 h-3 border-2 border-warning border-t-transparent rounded-full animate-spin" />
                                : <ArrowDown className="w-3 h-3" />}
                              Demote
                            </button>
                          )}
                          {(!isManagement || !PROTECTED_ROLES.includes(emp.role)) && (
                            <>
                              <button
                                onClick={() => setEditTarget(emp)}
                                className="p-1.5 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                                title="Edit"
                              >
                                <Pencil className="w-3.5 h-3.5" />
                              </button>
                              {(lc === 'active' || lc === 'deactivated') && (
                                <button
                                  onClick={() => handleToggleActive(emp)}
                                  className={`text-xs font-medium px-2 py-1 rounded-lg transition-colors ${
                                    lc === 'active'
                                      ? 'text-danger hover:bg-danger/10'
                                      : 'text-success hover:bg-success/10'
                                  }`}
                                >
                                  {lc === 'active' ? 'Deactivate' : 'Reactivate'}
                                </button>
                              )}
                              {isAdmin && (
                                <button
                                  onClick={() => handleDelete(emp)}
                                  className="p-1.5 rounded-lg hover:bg-danger/10 text-muted-foreground hover:text-danger transition-colors"
                                  title="Delete employee"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-border">
              <p className="text-xs text-subtle">
                {currentPage * PEOPLE_PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PEOPLE_PAGE_SIZE, visible.length)} of {visible.length} employees
              </p>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(p => p - 1)}
                  disabled={currentPage === 0}
                  className="px-3 py-1.5 text-xs rounded-lg border border-border hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  Previous
                </button>
                {Array.from({ length: totalPages }).map((_, i) => (
                  <button
                    key={i}
                    onClick={() => setPage(i)}
                    className={`w-7 h-7 text-xs rounded-lg border transition-colors ${
                      i === currentPage
                        ? 'bg-primary text-white border-primary'
                        : 'border-border hover:bg-accent'
                    }`}
                  >
                    {i + 1}
                  </button>
                ))}
                <button
                  onClick={() => setPage(p => p + 1)}
                  disabled={currentPage >= totalPages - 1}
                  className="px-3 py-1.5 text-xs rounded-lg border border-border hover:bg-accent disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Modals */}
      {showModal && (
        <EmployeeModal
          isCreate={true}
          onSave={handleCreate}
          onClose={() => setShowModal(false)}
          allowedRoles={allowedRoles}
        />
      )}
      {editTarget && (
        <EmployeeModal
          isCreate={false}
          initial={editTarget}
          onSave={handleEdit}
          onClose={() => setEditTarget(null)}
          allowedRoles={allowedRoles}
        />
      )}
      {showImport && (
        <BulkImportModal
          onClose={() => setShowImport(false)}
          onComplete={() => { setShowImport(false); load(); }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fleet Tab
// ---------------------------------------------------------------------------

function CopyableId({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };
  return (
    <button
      onClick={copy}
      className="group flex items-center gap-1.5 font-mono text-xs text-muted-foreground bg-accent/60 hover:bg-accent border border-border px-2.5 py-1 rounded-lg transition-colors"
      title="Copy channel ID"
    >
      <Hash className="w-3 h-3 shrink-0 text-muted-foreground/60" />
      <span className="truncate max-w-[140px]">{value}</span>
      {copied
        ? <Check className="w-3 h-3 text-success shrink-0" />
        : <Copy className="w-3 h-3 shrink-0 opacity-0 group-hover:opacity-60 transition-opacity" />}
    </button>
  );
}

const BOROUGH_OPTIONS = [
  { value: 'manhattan', label: 'Manhattan' },
  { value: 'queens',    label: 'Queens' },
  { value: 'brooklyn',  label: 'Brooklyn' },
  { value: 'bronx',     label: 'Bronx' },
  { value: 'staten island', label: 'Staten Island' },
];

function TruckAnchorModal({
  truck,
  onClose,
  onUpdated,
}: {
  truck: TruckRecord;
  onClose: () => void;
  onUpdated: (t: TruckRecord) => void;
}) {
  const [address, setAddress] = useState(truck.initial_anchor_display_address ?? truck.initial_anchor_address ?? '');
  const [borough, setBorough] = useState('manhattan');
  const [saving, setSaving]   = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  const hasAnchor = truck.initial_anchor_lat != null;

  async function save() {
    const trimmed = address.trim();
    if (!trimmed) { setError('Enter a street address or intersection.'); return; }
    setSaving(true);
    setError(null);
    try {
      const { data } = await axiosClient.patch<TruckRecord>(`/trucks/${truck.id}/anchor`, {
        address: trimmed,
        borough,
      });
      onUpdated(data);
      onClose();
    } catch (e: any) {
      setError(errorText(e, 'Geocoding failed. Check the address and try again.'));
    } finally {
      setSaving(false);
    }
  }

  async function clear() {
    setClearing(true);
    setError(null);
    try {
      const { data } = await axiosClient.patch<TruckRecord>(`/trucks/${truck.id}/anchor`, { address: null });
      onUpdated(data);
      onClose();
    } catch (e: any) {
      setError(errorText(e, 'Failed to clear anchor.'));
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MapPin className="w-4 h-4 text-primary" />
            <h3 className="font-semibold text-foreground">{hasAnchor ? 'Update' : 'Set'} anchor — {truck.name}</h3>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-accent text-muted-foreground">
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-muted-foreground">
          Enter a street intersection (preferred) or a street address for this
          truck's home territory. The system geocodes it to coordinates automatically.
        </p>
        <div className="p-2.5 bg-accent/40 rounded-xl space-y-1">
          <p className="text-[11px] font-medium text-muted-foreground">Format guide (GeoClient compatible)</p>
          <p className="text-[11px] text-muted-foreground">Address: <span className="font-mono text-foreground">411 W 36 ST</span> · <span className="font-mono text-foreground">250 BROADWAY</span></p>
          <p className="text-[11px] text-muted-foreground">Intersection (preferred): <span className="font-mono text-foreground">W 28 ST &amp; 9 AVE</span> · <span className="font-mono text-foreground">28th St and 9th Ave</span></p>
          <p className="text-[11px] text-muted-foreground">Intersections pin the corner itself — territory boundaries then fall midway between anchors.</p>
        </div>

        {hasAnchor && (
          <div className="flex items-start gap-2 p-2.5 bg-success/5 border border-success/20 rounded-xl">
            <MapPin className="w-3.5 h-3.5 text-success shrink-0 mt-0.5" />
            <div className="text-xs space-y-0.5">
              <p className="text-foreground font-medium">
                {truck.initial_anchor_display_address ?? truck.initial_anchor_address}
              </p>
              {truck.initial_anchor_display_address && truck.initial_anchor_address &&
                truck.initial_anchor_display_address !== truck.initial_anchor_address && (
                <p className="text-muted-foreground text-[10px]">
                  Normalised: {truck.initial_anchor_address}
                </p>
              )}
              <p className="text-muted-foreground font-mono">
                {truck.initial_anchor_lat?.toFixed(5)}, {truck.initial_anchor_lng?.toFixed(5)}
              </p>
            </div>
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Intersection or address</label>
            <input
              type="text"
              className="input w-full"
              placeholder="e.g. 411 W 36 ST"
              value={address}
              onChange={e => setAddress(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && save()}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Borough</label>
            <select className="input w-full" value={borough} onChange={e => setBorough(e.target.value)}>
              {BOROUGH_OPTIONS.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
            </select>
          </div>
        </div>

        {error && <p className="text-xs text-destructive">{error}</p>}

        <div className="flex gap-2 justify-between">
          {hasAnchor && (
            <button
              onClick={clear}
              disabled={clearing || saving}
              className="btn-secondary text-sm text-destructive flex items-center gap-1.5"
            >
              {clearing && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Clear
            </button>
          )}
          <div className="flex gap-2 ml-auto">
            <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
            <button
              onClick={save}
              disabled={saving || clearing}
              className="btn-primary text-sm flex items-center gap-1.5"
            >
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {saving ? 'Geocoding…' : 'Save anchor'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TruckAnchor2Modal({
  truck,
  onClose,
  onUpdated,
}: {
  truck: TruckRecord;
  onClose: () => void;
  onUpdated: (t: TruckRecord) => void;
}) {
  const [address, setAddress] = useState(truck.initial_anchor2_display_address ?? truck.initial_anchor2_address ?? '');
  const [borough, setBorough] = useState('manhattan');
  const [saving, setSaving]   = useState(false);
  const [clearing, setClearing] = useState(false);
  const [error, setError]     = useState<string | null>(null);

  const hasAnchor2 = truck.initial_anchor2_lat != null;

  async function save() {
    const trimmed = address.trim();
    if (!trimmed) { setError('Enter a street address or intersection.'); return; }
    setSaving(true);
    setError(null);
    try {
      const { data } = await axiosClient.patch<TruckRecord>(`/trucks/${truck.id}/anchor2`, {
        address: trimmed,
        borough,
      });
      onUpdated(data);
      onClose();
    } catch (e: any) {
      setError(errorText(e, 'Geocoding failed. Check the address and try again.'));
    } finally {
      setSaving(false);
    }
  }

  async function clear() {
    setClearing(true);
    setError(null);
    try {
      const { data } = await axiosClient.patch<TruckRecord>(`/trucks/${truck.id}/anchor2`, { address: null });
      onUpdated(data);
      onClose();
    } catch (e: any) {
      setError(errorText(e, 'Failed to clear anchor.'));
    } finally {
      setClearing(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MapPin className="w-4 h-4 text-info" />
            <h3 className="font-semibold text-foreground">{hasAnchor2 ? 'Update' : 'Set'} anchor 2 — {truck.name}</h3>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-accent text-muted-foreground">
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-muted-foreground">
          Optional second territory anchor for trucks that split across two distinct sub-zones.
          When set, the truck can receive a second zone around this point when tote geography
          supports the split.
        </p>
        <div className="p-2.5 bg-accent/40 rounded-xl space-y-1">
          <p className="text-[11px] font-medium text-muted-foreground">Format guide (GeoClient compatible)</p>
          <p className="text-[11px] text-muted-foreground">Address: <span className="font-mono text-foreground">411 W 36 ST</span> · <span className="font-mono text-foreground">250 BROADWAY</span></p>
          <p className="text-[11px] text-muted-foreground">Intersection (preferred): <span className="font-mono text-foreground">W 28 ST &amp; 9 AVE</span> · <span className="font-mono text-foreground">28th St and 9th Ave</span></p>
          <p className="text-[11px] text-muted-foreground">Intersections pin the corner itself — territory boundaries then fall midway between anchors.</p>
        </div>

        {hasAnchor2 && (
          <div className="flex items-start gap-2 p-2.5 bg-info/5 border border-info/20 rounded-xl">
            <MapPin className="w-3.5 h-3.5 text-info shrink-0 mt-0.5" />
            <div className="text-xs space-y-0.5">
              <p className="text-foreground font-medium">
                {truck.initial_anchor2_display_address ?? truck.initial_anchor2_address}
              </p>
              {truck.initial_anchor2_display_address && truck.initial_anchor2_address &&
                truck.initial_anchor2_display_address !== truck.initial_anchor2_address && (
                <p className="text-muted-foreground text-[10px]">
                  Normalised: {truck.initial_anchor2_address}
                </p>
              )}
              <p className="text-muted-foreground font-mono">
                {truck.initial_anchor2_lat?.toFixed(5)}, {truck.initial_anchor2_lng?.toFixed(5)}
              </p>
            </div>
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Intersection or address</label>
            <input
              type="text"
              className="input w-full"
              placeholder="e.g. 800 W 50 ST"
              value={address}
              onChange={e => setAddress(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && save()}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground mb-1 block">Borough</label>
            <select className="input w-full" value={borough} onChange={e => setBorough(e.target.value)}>
              {BOROUGH_OPTIONS.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
            </select>
          </div>
        </div>

        {error && <p className="text-xs text-destructive">{error}</p>}

        <div className="flex gap-2 justify-between">
          {hasAnchor2 && (
            <button
              onClick={clear}
              disabled={clearing || saving}
              className="btn-secondary text-sm text-destructive flex items-center gap-1.5"
            >
              {clearing && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              Clear
            </button>
          )}
          <div className="flex gap-2 ml-auto">
            <button onClick={onClose} className="btn-secondary text-sm">Cancel</button>
            <button
              onClick={save}
              disabled={saving || clearing}
              className="btn-primary text-sm flex items-center gap-1.5"
            >
              {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              {saving ? 'Geocoding…' : 'Save anchor 2'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function TruckCard({
  truck,
  onEdit,
  onAnchor,
  onAnchor2,
  onDeactivate,
  onReactivate,
}: {
  truck: TruckRecord;
  onEdit: () => void;
  onAnchor: () => void;
  onAnchor2: () => void;
  onDeactivate: () => void;
  onReactivate: () => void;
}) {
  return (
    <div className={`card group flex flex-col gap-3 transition-all hover:shadow-md ${!truck.is_active ? 'opacity-60' : ''}`}>
      {/* Top row: icon + name + edit */}
      <div className="flex items-start gap-3">
        <div className={`shrink-0 w-10 h-10 rounded-xl flex items-center justify-center ${
          truck.is_active ? 'bg-primary/10' : 'bg-accent'
        }`}>
          <Truck className={`w-5 h-5 ${truck.is_active ? 'text-primary' : 'text-muted-foreground'}`} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground truncate">{truck.name}</p>
          <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-full mt-1 ${
            truck.is_active
              ? 'bg-success/10 text-success'
              : 'bg-accent text-muted-foreground'
          }`}>
            {truck.is_active
              ? <><CheckCircle2 className="w-3 h-3" /> Active</>
              : 'Inactive'}
          </span>
        </div>
        <button
          onClick={onEdit}
          className="shrink-0 p-1.5 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground transition-colors opacity-0 group-hover:opacity-100"
          title="Edit truck"
        >
          <Pencil className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Discord row */}
      <div className="flex items-center gap-2 min-w-0">
        {truck.discord_channel_id ? (
          <CopyableId value={truck.discord_channel_id} />
        ) : (
          <span className="flex items-center gap-1 text-xs text-warning bg-warning/8 border border-warning/20 px-2.5 py-1 rounded-lg">
            <AlertTriangle className="w-3 h-3 shrink-0" /> No Discord channel
          </span>
        )}
      </div>

      {/* Anchor 1 row */}
      <div className="min-w-0">
        {truck.initial_anchor_lat != null ? (
          <button
            onClick={onAnchor}
            className="group/ap flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full text-left"
            title="Edit anchor point 1"
          >
            <MapPin className="w-3 h-3 text-success shrink-0" />
            <span className="truncate">{truck.initial_anchor_display_address ?? truck.initial_anchor_address}</span>
            <Pencil className="w-3 h-3 shrink-0 opacity-0 group-hover/ap:opacity-60 transition-opacity ml-auto" />
          </button>
        ) : (
          <button
            onClick={onAnchor}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary transition-colors"
          >
            <MapPin className="w-3 h-3 shrink-0 opacity-50" />
            <span>Set anchor point</span>
          </button>
        )}
      </div>

      {/* Anchor 2 row — optional secondary zone seed */}
      <div className="min-w-0">
        {truck.initial_anchor2_lat != null ? (
          <button
            onClick={onAnchor2}
            className="group/ap2 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full text-left"
            title="Edit anchor point 2"
          >
            <MapPin className="w-3 h-3 text-info shrink-0" />
            <span className="truncate">{truck.initial_anchor2_display_address ?? truck.initial_anchor2_address}</span>
            <Pencil className="w-3 h-3 shrink-0 opacity-0 group-hover/ap2:opacity-60 transition-opacity ml-auto" />
          </button>
        ) : (
          <button
            onClick={onAnchor2}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-info transition-colors"
            title="Add a second territory anchor to split this truck across two zones"
          >
            <MapPin className="w-3 h-3 shrink-0 opacity-30" />
            <span className="opacity-60">Add anchor 2</span>
          </button>
        )}
      </div>

      {/* Footer: toggle */}
      <div className="pt-1 border-t border-border">
        {truck.is_active ? (
          <button
            onClick={onDeactivate}
            className="flex items-center gap-1.5 text-xs font-medium text-danger hover:bg-danger/8 px-2 py-1 rounded-lg transition-colors w-full"
          >
            <ToggleRight className="w-3.5 h-3.5" /> Deactivate
          </button>
        ) : (
          <button
            onClick={onReactivate}
            className="flex items-center gap-1.5 text-xs font-medium text-success hover:bg-success/8 px-2 py-1 rounded-lg transition-colors w-full"
          >
            <ToggleLeft className="w-3.5 h-3.5" /> Reactivate
          </button>
        )}
      </div>
    </div>
  );
}

function FleetTab() {
  const { confirmState: fleetConfirmState, confirm: fleetConfirm, cancelConfirm: fleetCancelConfirm } = useConfirm();
  const [trucks, setTrucks]             = useState<TruckRecord[]>([]);
  const [loading, setLoading]           = useState(true);
  const [loadError, setLoadError]       = useState<string | null>(null);
  const [showModal, setShowModal]       = useState(false);
  const [editTarget, setEditTarget]     = useState<TruckRecord | null>(null);
  const [anchorTarget, setAnchorTarget]   = useState<TruckRecord | null>(null);
  const [anchor2Target, setAnchor2Target] = useState<TruckRecord | null>(null);
  const [search, setSearch]               = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'inactive'>('all');

  const load = () => {
    setLoading(true);
    setLoadError(null);
    axiosClient.get('/trucks/?include_inactive=true')
      .then(r => setTrucks(r.data))
      .catch(() => setLoadError('Failed to load fleet. Check your connection and try again.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (data: { name: string; discord_channel_id: string | null }) => {
    const res = await axiosClient.post('/trucks/', data);
    setTrucks(prev => [...prev, res.data]);
    setShowModal(false);
  };

  const handleEdit = async (data: { name: string; discord_channel_id: string | null }) => {
    if (!editTarget) return;
    const res = await axiosClient.put(`/trucks/${editTarget.id}`, data);
    setTrucks(prev => prev.map(t => t.id === editTarget.id ? res.data : t));
    setEditTarget(null);
  };

  const handleDeactivate = async (truck: TruckRecord) => {
    const ok = await fleetConfirm({
      title: 'Deactivate Truck',
      message: `Deactivate ${truck.name}? It will be removed from future dispatch until reactivated.`,
      confirmLabel: 'Deactivate',
      variant: 'danger',
    });
    if (!ok) return;
    const res = await axiosClient.put(`/trucks/${truck.id}/deactivate`);
    setTrucks(prev => prev.map(t => t.id === truck.id ? res.data : t));
  };

  const handleReactivate = async (truck: TruckRecord) => {
    const res = await axiosClient.put(`/trucks/${truck.id}/reactivate`);
    setTrucks(prev => prev.map(t => t.id === truck.id ? res.data : t));
  };

  const activeCount   = trucks.filter(t => t.is_active).length;
  const inactiveCount = trucks.filter(t => !t.is_active).length;
  const discordLinked = trucks.filter(t => t.discord_channel_id).length;

  const visible = trucks.filter(t => {
    const matchStatus = statusFilter === 'all'
      || (statusFilter === 'active' && t.is_active)
      || (statusFilter === 'inactive' && !t.is_active);
    const matchSearch = !search || t.name.toLowerCase().includes(search.toLowerCase());
    return matchStatus && matchSearch;
  });

  return (
    <div className="space-y-5">
      <ConfirmDialog {...fleetConfirmState} onCancel={fleetCancelConfirm} />

      {/* Summary KPIs */}
      <div className="grid grid-cols-3 gap-3">
        {[
          { label: 'Active',          value: activeCount,   color: 'text-success', filter: 'active'   as const },
          { label: 'Inactive',        value: inactiveCount, color: 'text-muted-foreground', filter: 'inactive' as const },
          { label: 'Discord Linked',  value: discordLinked, color: 'text-primary', filter: 'all'      as const },
        ].map(({ label, value, color, filter }) => (
          <button
            key={label}
            onClick={() => setStatusFilter(prev => prev === filter && label !== 'Discord Linked' ? 'all' : filter)}
            className={`card text-center py-3 transition-colors hover:bg-accent/50 ${statusFilter === filter && label !== 'Discord Linked' ? 'ring-2 ring-primary/30' : ''}`}
          >
            <p className={`text-2xl font-bold ${color}`}>{value}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
          </button>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <input
            type="search"
            placeholder="Search trucks…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="input pl-8 w-full"
          />
        </div>
        <div className="relative">
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value as typeof statusFilter)}
            className="input pr-8 appearance-none"
          >
            <option value="all">All</option>
            <option value="active">Active only</option>
            <option value="inactive">Inactive only</option>
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
        </div>
        <button onClick={load} className="btn-ghost text-muted-foreground p-2" title="Refresh">
          <RefreshCw className="w-4 h-4" />
        </button>
        <button
          onClick={() => setShowModal(true)}
          className="btn-primary flex items-center gap-2 ml-auto"
        >
          <Plus className="w-4 h-4" /> Add Truck
        </button>
      </div>

      {loadError && (
        <div className="card border-danger/30 bg-danger/5 text-danger text-sm px-4 py-3 rounded-xl flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" /> {loadError}
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {[0,1,2,3,4,5,6].map(i => (
            <div key={i} className="card animate-pulse h-32 bg-accent/40" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="card text-center py-16 space-y-2">
          <Truck className="w-8 h-8 text-muted-foreground mx-auto" />
          <p className="text-muted-foreground text-sm">
            {trucks.length === 0 ? 'No trucks in the fleet yet.' : 'No trucks match your filter.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {visible.map(truck => (
            <TruckCard
              key={truck.id}
              truck={truck}
              onEdit={() => setEditTarget(truck)}
              onAnchor={() => setAnchorTarget(truck)}
              onAnchor2={() => setAnchor2Target(truck)}
              onDeactivate={() => handleDeactivate(truck)}
              onReactivate={() => handleReactivate(truck)}
            />
          ))}
        </div>
      )}

      {showModal && (
        <TruckModal
          isCreate={true}
          onSave={handleCreate}
          onClose={() => setShowModal(false)}
        />
      )}
      {editTarget && (
        <TruckModal
          isCreate={false}
          initial={editTarget}
          onSave={handleEdit}
          onClose={() => setEditTarget(null)}
        />
      )}
      {anchorTarget && (
        <TruckAnchorModal
          truck={anchorTarget}
          onClose={() => setAnchorTarget(null)}
          onUpdated={updated => {
            setTrucks(prev => prev.map(t => t.id === updated.id ? updated : t));
            setAnchorTarget(null);
          }}
        />
      )}
      {anchor2Target && (
        <TruckAnchor2Modal
          truck={anchor2Target}
          onClose={() => setAnchor2Target(null)}
          onUpdated={updated => {
            setTrucks(prev => prev.map(t => t.id === updated.id ? updated : t));
            setAnchor2Target(null);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// System Tab
// ---------------------------------------------------------------------------

const BOROUGH_PRESETS: Record<string, { sw_lat: number; sw_lng: number; ne_lat: number; ne_lng: number }> = {
  manhattan: { sw_lat: 40.6995, sw_lng: -74.0196, ne_lat: 40.8820, ne_lng: -73.9070 },
  queens:    { sw_lat: 40.5420, sw_lng: -73.9626, ne_lat: 40.8007, ne_lng: -73.7004 },
  brooklyn:  { sw_lat: 40.5707, sw_lng: -74.0421, ne_lat: 40.7394, ne_lng: -73.8330 },
  bronx:     { sw_lat: 40.7855, sw_lng: -73.9338, ne_lat: 40.9176, ne_lng: -73.7654 },
};

type EditTab = 'draw' | 'intersections' | 'advanced';

interface IntersectionRow { street: string; avenue: string; }

function CompanyZoneCard({ isAdmin }: { isAdmin: boolean }) {
  const { isLoading: authLoading } = useAuth();
  const [zone, setZone]     = useState<CompanyZone | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [editTab, setEditTab] = useState<EditTab>('draw');

  // Draw mode state — corners committed from the map
  const [drawnCorners, setDrawnCorners] = useState<CornerPoint[]>([]);

  // Intersection list state
  const [borough, setBorough]       = useState('manhattan');
  const [intersections, setIntersections] = useState<IntersectionRow[]>([
    { street: '', avenue: '' },
    { street: '', avenue: '' },
    { street: '', avenue: '' },
  ]);

  // Advanced raw-coord state
  const [swLat, setSwLat] = useState('');
  const [swLng, setSwLng] = useState('');
  const [neLat, setNeLat] = useState('');
  const [neLng, setNeLng] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await axiosClient.get<CompanyZone | null>('/sort/company-zone');
      setError(null);
      setZone(data);
      if (data) {
        setSwLat(data.sw_lat.toFixed(6));
        setSwLng(data.sw_lng.toFixed(6));
        setNeLat(data.ne_lat.toFixed(6));
        setNeLng(data.ne_lng.toFixed(6));
        if (data.corners && data.corners.length >= 3) {
          setDrawnCorners(data.corners);
        }
      }
    } catch (e: any) {
      const status = e?.response?.status;
      if (status !== 404) {
        setError(`Failed to load operating zone (HTTP ${status ?? 'network error'}).`);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (!authLoading) load(); }, [load, authLoading]);

  function cacheZone(z: CompanyZone) {
    try { localStorage.setItem('asheflow.companyZone.v1', JSON.stringify(z)); } catch {}
  }

  function onDrawSave(corners: CornerPoint[]) {
    setDrawnCorners(corners);
  }

  async function commitDrawn() {
    if (drawnCorners.length < 3) { setError('Draw at least 3 vertices on the map.'); return; }
    setSaving(true); setError(null); setSuccess(false);
    try {
      const { data } = await axiosClient.post<CompanyZone>('/sort/company-zone/from-corners', {
        corners: drawnCorners,
      });
      cacheZone(data); setZone(data); setEditing(false);
      setSuccess(true); setTimeout(() => setSuccess(false), 3000);
    } catch (e: any) {
      const detail = errorText(e, '') || undefined;
      setError(typeof detail === 'string' ? detail : `Save failed (HTTP ${e?.response?.status ?? 'unknown'}).`);
    } finally { setSaving(false); }
  }

  async function saveFromIntersections() {
    const filled = intersections.filter(r => r.street.trim() && r.avenue.trim());
    if (filled.length < 3) { setError('Enter at least 3 complete intersections.'); return; }
    setSaving(true); setError(null); setSuccess(false);
    try {
      const { data } = await axiosClient.post<CompanyZone>('/sort/company-zone/from-intersections', {
        intersections: filled.map(r => ({ street: r.street.trim(), avenue: r.avenue.trim() })),
        borough,
      });
      cacheZone(data); setZone(data); setEditing(false);
      setSuccess(true); setTimeout(() => setSuccess(false), 3000);
    } catch (e: any) {
      setError(errorText(e, `Save failed (HTTP ${e?.response?.status ?? 'unknown'}).`));
    } finally { setSaving(false); }
  }

  async function saveFromCoords() {
    setSaving(true); setError(null); setSuccess(false);
    try {
      const { data } = await axiosClient.post<CompanyZone>('/sort/company-zone', {
        sw_lat: parseFloat(swLat), sw_lng: parseFloat(swLng),
        ne_lat: parseFloat(neLat), ne_lng: parseFloat(neLng),
      });
      cacheZone(data); setZone(data); setEditing(false);
      setSuccess(true); setTimeout(() => setSuccess(false), 3000);
    } catch (e: any) {
      setError(errorText(e, `Save failed (HTTP ${e?.response?.status ?? 'unknown'}).`));
    } finally { setSaving(false); }
  }

  function updateIntersection(i: number, field: 'street' | 'avenue', value: string) {
    setIntersections(prev => { const next = [...prev]; next[i] = { ...next[i], [field]: value }; return next; });
  }

  function addIntersection() {
    setIntersections(prev => [...prev, { street: '', avenue: '' }]);
  }

  function removeIntersection(i: number) {
    setIntersections(prev => prev.filter((_, idx) => idx !== i));
  }

  const editTabs: { key: EditTab; label: string; icon: React.ElementType }[] = [
    { key: 'draw',          label: 'Draw on map',    icon: MousePointer2 },
    { key: 'intersections', label: 'Street entries', icon: Navigation    },
    { key: 'advanced',      label: 'Coordinates',    icon: MapPin        },
  ];

  return (
    <div className="card space-y-4">
      <div className="flex items-center justify-between border-b border-border pb-3">
        <div className="flex items-center gap-2">
          <Map className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Operating Zone</h2>
        </div>
        {isAdmin && !editing && (
          <button
            onClick={() => { setEditing(true); setError(null); }}
            className="flex items-center gap-1.5 text-xs text-primary hover:bg-primary/10 px-2.5 py-1.5 rounded-lg transition-colors"
          >
            <Pencil className="w-3.5 h-3.5" /> {zone ? 'Edit' : 'Configure'}
          </button>
        )}
      </div>

      <p className="text-sm text-muted-foreground">
        The polygon that defines your company's delivery area.
        Used by the sort algorithm to detect out-of-area packages.
        {!isAdmin && ' Contact your admin to configure this.'}
      </p>

      {error && !editing && (
        <div className="flex items-center gap-2 p-3 bg-destructive/5 border border-destructive/20 rounded-xl text-xs text-destructive">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" /> {error}
        </div>
      )}

      {/* ── View mode ── */}
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : zone && !editing ? (
        <div className="space-y-2">
          <CompanyZoneMap mode="view" bounds={zone} className="w-full h-[520px]" />
          {zone.corners && zone.corners.length >= 3 ? (
            <div className="space-y-1.5">
              <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
                {zone.corners.length} vertices
              </p>
              <div className="grid grid-cols-2 gap-2">
                {zone.corners.map((c, i) => (
                  <div key={i} className="p-2.5 bg-accent/40 rounded-xl space-y-0.5">
                    <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">Vertex {i + 1}</p>
                    <p className="text-xs font-mono text-foreground">{c.lat.toFixed(5)}, {c.lng.toFixed(5)}</p>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: 'SW corner', lat: zone.sw_lat, lng: zone.sw_lng },
                { label: 'NE corner', lat: zone.ne_lat, lng: zone.ne_lng },
              ].map(({ label, lat, lng }) => (
                <div key={label} className="p-2.5 bg-accent/40 rounded-xl space-y-0.5">
                  <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">{label}</p>
                  <p className="text-xs font-mono text-foreground">{lat.toFixed(5)}, {lng.toFixed(5)}</p>
                </div>
              ))}
            </div>
          )}
          {success && (
            <div className="flex items-center gap-2 text-xs text-success bg-success/10 border border-success/20 rounded-xl px-3 py-2">
              <CheckCircle2 className="w-3.5 h-3.5 shrink-0" /> Operating zone saved.
            </div>
          )}
        </div>
      ) : !zone && !editing ? (
        <div className="flex items-center gap-2 p-3 bg-warning/5 border border-warning/20 rounded-xl text-xs text-warning">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          No operating zone configured — overflow detection is disabled.
        </div>
      ) : null}

      {/* ── Edit mode ── */}
      {editing && isAdmin && (
        <div className="space-y-4">
          {/* Tab bar */}
          <div className="flex items-center gap-1 bg-accent rounded-xl p-1">
            {editTabs.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => { setEditTab(key); setError(null); }}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex-1 justify-center ${
                  editTab === key
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
          </div>

          {/* ── Draw tab ── */}
          {editTab === 'draw' && (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Click anywhere on the map to place vertices. Drag markers to adjust. Minimum 3 points.
                {drawnCorners.length >= 3 && (
                  <span className="ml-1 text-success font-medium">
                    {drawnCorners.length} vertices ready — click "Save zone" to confirm.
                  </span>
                )}
              </p>
              <CompanyZoneMap
                mode="draw"
                initialCorners={drawnCorners.length > 0 ? drawnCorners : zone?.corners}
                onSave={onDrawSave}
                onCancel={() => setEditing(false)}
                className="w-full h-[480px]"
              />
            </div>
          )}

          {/* ── Intersections tab ── */}
          {editTab === 'intersections' && (
            <div className="space-y-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Borough</label>
                <select className="input w-full text-sm" value={borough} onChange={e => setBorough(e.target.value)}>
                  {BOROUGH_OPTIONS.map(b => <option key={b.value} value={b.value}>{b.label}</option>)}
                </select>
              </div>

              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">
                  Enter intersections in order around the perimeter (min 3):
                </p>
                {intersections.map((row, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-[10px] text-muted-foreground w-5 shrink-0 text-right">{i + 1}.</span>
                    <input
                      type="text"
                      className="input text-sm flex-1"
                      placeholder="Street, e.g. W 23 ST"
                      value={row.street}
                      onChange={e => updateIntersection(i, 'street', e.target.value)}
                    />
                    <span className="text-xs text-muted-foreground shrink-0">&amp;</span>
                    <input
                      type="text"
                      className="input text-sm flex-1"
                      placeholder="Avenue, e.g. 10 AVE"
                      value={row.avenue}
                      onChange={e => updateIntersection(i, 'avenue', e.target.value)}
                    />
                    {intersections.length > 3 && (
                      <button onClick={() => removeIntersection(i)} className="text-muted-foreground hover:text-destructive transition-colors shrink-0">
                        <X className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                ))}
                <button
                  onClick={addIntersection}
                  className="text-xs text-primary hover:bg-primary/10 px-2.5 py-1.5 rounded-lg transition-colors flex items-center gap-1"
                >
                  <Plus className="w-3 h-3" /> Add intersection
                </button>
              </div>

              <div className="p-2.5 bg-accent/40 rounded-xl space-y-1">
                <p className="text-[11px] font-medium text-muted-foreground">Format guide</p>
                <p className="text-[11px] text-muted-foreground">Streets: <span className="font-mono text-foreground">W 23 ST</span>, <span className="font-mono text-foreground">FULTON ST</span></p>
                <p className="text-[11px] text-muted-foreground">Avenues: <span className="font-mono text-foreground">6 AVE</span>, <span className="font-mono text-foreground">12 AVE</span>, <span className="font-mono text-foreground">BROADWAY</span></p>
                <p className="text-[11px] text-muted-foreground">List vertices in order around the perimeter — the polygon closes automatically.</p>
              </div>
            </div>
          )}

          {/* ── Advanced tab ── */}
          {editTab === 'advanced' && (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Enter SW and NE bounding-box corners directly. Right-click any point on Google Maps to copy coordinates.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">SW corner — bottom-left</p>
                  <input type="number" step="any" placeholder="Latitude" value={swLat}
                    onChange={e => setSwLat(e.target.value)} className="input w-full text-sm font-mono" />
                  <input type="number" step="any" placeholder="Longitude" value={swLng}
                    onChange={e => setSwLng(e.target.value)} className="input w-full text-sm font-mono" />
                </div>
                <div className="space-y-1">
                  <p className="text-xs font-medium text-muted-foreground">NE corner — top-right</p>
                  <input type="number" step="any" placeholder="Latitude" value={neLat}
                    onChange={e => setNeLat(e.target.value)} className="input w-full text-sm font-mono" />
                  <input type="number" step="any" placeholder="Longitude" value={neLng}
                    onChange={e => setNeLng(e.target.value)} className="input w-full text-sm font-mono" />
                </div>
              </div>
            </div>
          )}

          {error && <p className="text-xs text-destructive">{error}</p>}

          <div className="flex gap-2 justify-end border-t border-border pt-3">
            <button
              onClick={() => { setEditing(false); setError(null); }}
              className="btn-secondary text-sm"
            >
              Cancel
            </button>
            {editTab === 'draw' && (
              <button
                onClick={commitDrawn}
                disabled={saving || drawnCorners.length < 3}
                className="btn-primary text-sm flex items-center gap-1.5 disabled:opacity-50"
              >
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {saving ? 'Saving…' : `Save zone${drawnCorners.length >= 3 ? ` (${drawnCorners.length} vertices)` : ''}`}
              </button>
            )}
            {editTab === 'intersections' && (
              <button
                onClick={saveFromIntersections}
                disabled={saving}
                className="btn-primary text-sm flex items-center gap-1.5"
              >
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {saving ? 'Geocoding…' : 'Save zone'}
              </button>
            )}
            {editTab === 'advanced' && (
              <button
                onClick={saveFromCoords}
                disabled={saving}
                className="btn-primary text-sm flex items-center gap-1.5"
              >
                {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {saving ? 'Saving…' : 'Save zone'}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function SystemTab() {
  const { groups } = useAuth();
  const isAdmin = groups.includes('admin');
  const { confirmState: sysConfirmState, confirm: sysConfirm, cancelConfirm: sysCancelConfirm } = useConfirm();
  const [days, setDays]         = useState(30);
  const [pruning, setPruning]   = useState(false);
  const [result, setResult]     = useState<{ deleted: number; cutoff: string } | null>(null);
  const [error, setError]       = useState('');

  const handlePrune = async () => {
    const ok = await sysConfirm({
      title: 'Prune Notifications',
      message: `Delete all read notifications older than ${days} days? This cannot be undone.`,
      confirmLabel: 'Delete',
      variant: 'danger',
    });
    if (!ok) return;
    setPruning(true);
    setResult(null);
    setError('');
    try {
      const res = await axiosClient.delete(`/notifications/prune?days=${days}`);
      setResult(res.data);
    } catch (err: any) {
      setError(errorText(err, 'Something went wrong.'));
    } finally {
      setPruning(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <ConfirmDialog {...sysConfirmState} onCancel={sysCancelConfirm} />

      <CompanyZoneCard isAdmin={isAdmin} />

      <div className="card space-y-4">
        <div className="flex items-center gap-2 border-b border-border pb-3">
          <Trash2 className="w-4 h-4 text-danger" />
          <h2 className="text-sm font-semibold text-foreground">Prune Read Notifications</h2>
        </div>

        <p className="text-sm text-muted-foreground">
          Permanently delete read notifications older than the specified number of days.
          Unread notifications are never deleted.
        </p>

        <div className="flex items-center gap-3">
          <label className="text-sm font-medium text-foreground whitespace-nowrap">Older than</label>
          <input
            type="number"
            min={1}
            max={365}
            value={days}
            onChange={e => setDays(Math.max(1, Math.min(365, Number(e.target.value))))}
            className="input w-24 text-center"
          />
          <span className="text-sm text-muted-foreground">days</span>
        </div>

        {error && (
          <p className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-xl px-3 py-2">
            {error}
          </p>
        )}

        {result && (
          <div className="flex items-center gap-2 text-sm text-success bg-success/10 border border-success/20 rounded-xl px-3 py-2">
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            <span>
              {result.deleted === 0
                ? 'No notifications matched — nothing deleted.'
                : `Deleted ${result.deleted} notification${result.deleted !== 1 ? 's' : ''} older than ${result.cutoff}.`}
            </span>
          </div>
        )}

        <button
          onClick={handlePrune}
          disabled={pruning}
          className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-danger text-foreground hover:bg-danger/90 transition-colors disabled:opacity-50"
        >
          {pruning
            ? <div className="w-3.5 h-3.5 border-2 border-foreground border-t-transparent rounded-full animate-spin" />
            : <Trash2 className="w-3.5 h-3.5" />}
          {pruning ? 'Pruning…' : 'Run Prune'}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Assets Page
// ---------------------------------------------------------------------------

export default function Assets() {
  const [tab, setTab] = useState<Tab>('people');

  const tabs: { key: Tab; label: string; icon: React.ElementType }[] = [
    { key: 'people', label: 'People',  icon: Users },
    { key: 'fleet',  label: 'Fleet',   icon: Truck },
    { key: 'system', label: 'System',  icon: Settings },
  ];

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Header */}
      <div>
        <h1 className="page-title">Data Management</h1>
        <p className="text-subtle mt-1">Manage employees and fleet vehicles.</p>
      </div>

      {/* Tab bar */}
      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 w-fit">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === key
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'people' && <PeopleTab />}
      {tab === 'fleet'  && <FleetTab />}
      {tab === 'system' && <SystemTab />}
    </div>
  );
}
