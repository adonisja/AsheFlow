import React, { useState, useEffect } from 'react';
import {
  Users, Truck, Plus, Pencil, CheckCircle2, AlertTriangle,
  RefreshCw, X, ChevronDown, Settings, Trash2, FileUp, Mail, ArrowUp, ArrowDown,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { useAuth } from '../contexts/AuthContext';
import BulkImportModal from '../components/BulkImportModal';
import ConfirmDialog from '../components/ui/ConfirmDialog';
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
  discord_channel_id: number | null;
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

function badge(role: string) {
  const colors: Record<string, string> = {
    driver:     'bg-info/10 text-info',
    walker:     'bg-success/10 text-success',
    trainer:    'bg-violet/10 text-violet',
    trainee:    'bg-warning/10 text-warning',
    dispatch:   'bg-primary/10 text-primary',
    management: 'bg-teal/10 text-teal',
    admin:      'bg-danger/10 text-danger',
  };
  return `inline-block px-2 py-0.5 rounded-full text-xs font-medium capitalize ${colors[role] ?? 'bg-accent text-foreground'}`;
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
      setError(err?.response?.data?.detail ?? 'Something went wrong.');
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
  onSave: (data: { name: string; discord_channel_id: number | null }) => Promise<void>;
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
        discord_channel_id: channelId.trim() ? Number(channelId.trim()) : null,
      });
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Something went wrong.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-card w-full max-w-sm rounded-2xl border border-border shadow-xl animate-slide-up">
        <div className="flex items-center justify-between p-5 border-b border-border">
          <h2 className="font-semibold text-foreground">{isCreate ? 'Add Truck' : 'Edit Truck'}</h2>
          <button onClick={onClose} className="btn-ghost p-1.5"><X className="w-4 h-4" /></button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {error && (
            <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-xl px-3 py-2">
              {error}
            </div>
          )}

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Truck Name *</label>
            <input
              required
              value={name}
              onChange={e => setName(e.target.value)}
              className="input w-full"
              placeholder="Atlas"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Discord Channel ID
            </label>
            <input
              value={channelId}
              onChange={e => setChannelId(e.target.value)}
              className={`input w-full font-mono ${!channelIdValid ? 'border-danger/60 focus:ring-danger/30' : ''}`}
              placeholder="e.g. 1234567890123456789"
            />
            {!channelIdValid && (
              <p className="text-xs text-danger">Must be a valid Discord snowflake (17–20 digits).</p>
            )}
            {channelId && channelIdValid && (
              <p className="text-xs text-success flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" /> Channel linked
              </p>
            )}
            {!channelId && (
              <p className="text-xs text-muted-foreground">
                Right-click the channel in Discord → Copy Channel ID.
                {!isCreate && ' Leave blank to unlink.'}
              </p>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
            <button
              type="submit"
              disabled={saving || !channelIdValid}
              className="btn-primary flex items-center gap-2"
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
      setResendMsg({ id: emp.id, ok: false, text: err?.response?.data?.detail ?? 'Failed to send invite.' });
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
      setResendMsg({ id: emp.id, ok: false, text: err?.response?.data?.detail ?? 'Failed to resend credentials.' });
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
      setPromoteMsg({ id: emp.id, ok: false, text: err?.response?.data?.detail ?? 'Promotion failed.' });
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
      setPromoteMsg({ id: emp.id, ok: false, text: err?.response?.data?.detail ?? 'Demotion failed.' });
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
    const matchStatus = statusFilter === 'all' || getLifecycle(e) === statusFilter;
    return matchRole && matchSearch && matchStatus;
  });

  const totalPages  = Math.ceil(visible.length / PEOPLE_PAGE_SIZE);
  const currentPage = Math.min(page, Math.max(0, totalPages - 1));
  const pageSlice   = visible.slice(currentPage * PEOPLE_PAGE_SIZE, (currentPage + 1) * PEOPLE_PAGE_SIZE);

  return (
    <div className="space-y-5">
      <ConfirmDialog {...confirmState} onCancel={cancelConfirm} />
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="search"
          placeholder="Search name, email, Discord…"
          value={search}
          onChange={e => { setSearch(e.target.value); setPage(0); }}
          className="input flex-1 min-w-[180px] max-w-xs"
        />
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
            <option value="not_invited">Not Invited</option>
            <option value="invited">Invited</option>
            <option value="registered">Registered</option>
            <option value="active">Active</option>
            <option value="deactivated">Deactivated</option>
          </select>
          <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
        </div>
        <button onClick={load} className="btn-ghost text-muted-foreground flex items-center gap-2 text-sm">
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

      {/* Count */}
      <p className="text-xs text-subtle">
        {employees.filter(e => e.account_status === 'active' && e.is_active).length} active ·{' '}
        {employees.filter(e => e.account_status === 'pending_verification').length} pending ·{' '}
        {employees.filter(e => e.account_status === 'active' && !e.is_active).length} deactivated
        {visible.length !== employees.length && ` · ${visible.length} shown`}
      </p>

      {/* Table */}
      {loadError && (
        <div className="card border-danger/30 bg-danger/5 text-danger text-sm px-4 py-3 rounded-xl">{loadError}</div>
      )}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="w-7 h-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : visible.length === 0 ? (
        <div className="text-center py-16 text-subtle">No employees found.</div>
      ) : (
        <div className="card overflow-hidden p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wider border-b border-border bg-accent/30">
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Role</th>
                  <th className="px-4 py-3 hidden sm:table-cell">Email</th>
                  <th className="px-4 py-3 hidden md:table-cell">Discord ID</th>
                  <th className="px-4 py-3 hidden lg:table-cell">Phone</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {pageSlice.map(emp => (
                  <tr key={emp.id} className={`transition-colors hover:bg-accent/20 ${emp.account_status === 'active' && !emp.is_active ? 'opacity-50' : ''}`}>
                    <td className="px-4 py-3 font-medium text-foreground whitespace-nowrap">{emp.name}</td>
                    <td className="px-4 py-3">
                      <span className={badge(emp.role)}>{emp.role}</span>
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell text-muted-foreground text-xs truncate max-w-[180px]">
                      {emp.email ?? <span className="text-subtle italic">—</span>}
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell font-mono text-xs text-muted-foreground">
                      {emp.discord_id
                        ? emp.discord_id
                        : <span className="text-warning italic">not set</span>}
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell text-xs text-muted-foreground">
                      {emp.phone_number ?? <span className="text-subtle italic">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      {(() => {
                        const { label, cls } = LIFECYCLE_BADGE[getLifecycle(emp)];
                        return (
                          <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
                            {label}
                          </span>
                        );
                      })()}
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
                        {/* Resend invite — only for not-invited / invited states */}
                        {(getLifecycle(emp) === 'not_invited' || getLifecycle(emp) === 'invited') && emp.email && (
                          <button
                            onClick={() => handleResendInvite(emp)}
                            disabled={resendingId === emp.id}
                            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:bg-primary/10 px-2 py-1 rounded-lg transition-colors disabled:opacity-50"
                            title="Re-send registration invite email"
                          >
                            {resendingId === emp.id
                              ? <div className="w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                              : <Mail className="w-3 h-3" />}
                            {getLifecycle(emp) === 'not_invited' ? 'Send Invite' : 'Resend Invite'}
                          </button>
                        )}
                        {/* Resend credentials — only for registered state (form done, not yet signed in) */}
                        {getLifecycle(emp) === 'registered' && emp.email && (
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
                            {(getLifecycle(emp) === 'active' || getLifecycle(emp) === 'deactivated') && (
                              <button
                                onClick={() => handleToggleActive(emp)}
                                className={`text-xs font-medium px-2 py-1 rounded-lg transition-colors ${
                                  getLifecycle(emp) === 'active'
                                    ? 'text-danger hover:bg-danger/10'
                                    : 'text-success hover:bg-success/10'
                                }`}
                              >
                                {getLifecycle(emp) === 'active' ? 'Deactivate' : 'Reactivate'}
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
                ))}
              </tbody>
            </table>
          </div>
          {/* Pagination controls */}
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

function FleetTab() {
  const { confirmState: fleetConfirmState, confirm: fleetConfirm, cancelConfirm: fleetCancelConfirm } = useConfirm();
  const [trucks, setTrucks]           = useState<TruckRecord[]>([]);
  const [loading, setLoading]         = useState(true);
  const [loadError, setLoadError]     = useState<string | null>(null);
  const [showModal, setShowModal]     = useState(false);
  const [editTarget, setEditTarget]   = useState<TruckRecord | null>(null);

  const load = () => {
    setLoading(true);
    setLoadError(null);
    axiosClient.get('/trucks/?include_inactive=true')
      .then(r => setTrucks(r.data))
      .catch(() => setLoadError('Failed to load fleet. Check your connection and try again.'))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (data: { name: string; discord_channel_id: number | null }) => {
    const res = await axiosClient.post('/trucks/', data);
    setTrucks(prev => [...prev, res.data]);
    setShowModal(false);
  };

  const handleEdit = async (data: { name: string; discord_channel_id: number | null }) => {
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

  return (
    <div className="space-y-5">
      <ConfirmDialog {...fleetConfirmState} onCancel={fleetCancelConfirm} />
      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <button onClick={load} className="btn-ghost text-muted-foreground flex items-center gap-2 text-sm">
          <RefreshCw className="w-4 h-4" />
        </button>
        <button
          onClick={() => setShowModal(true)}
          className="btn-primary flex items-center gap-2 ml-auto"
        >
          <Plus className="w-4 h-4" /> Add Truck
        </button>
      </div>

      <p className="text-xs text-subtle">
        {trucks.filter(t => t.is_active).length} active · {trucks.filter(t => !t.is_active).length} inactive
      </p>

      {loadError && (
        <div className="card border-danger/30 bg-danger/5 text-danger text-sm px-4 py-3 rounded-xl">{loadError}</div>
      )}
      {loading ? (
        <div className="flex justify-center py-16">
          <div className="w-7 h-7 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        </div>
      ) : trucks.length === 0 ? (
        <div className="text-center py-16 text-subtle">No trucks in the fleet yet.</div>
      ) : (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
          {trucks.map(truck => (
            <div
              key={truck.id}
              className={`card p-4 space-y-3 flex flex-col items-center text-center transition-opacity ${
                !truck.is_active ? 'opacity-50' : ''
              }`}
            >
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                truck.is_active ? 'bg-primary/10' : 'bg-accent'
              }`}>
                <Truck className={`w-5 h-5 ${truck.is_active ? 'text-primary' : 'text-muted-foreground'}`} />
              </div>
              <div>
                <p className="text-sm font-semibold text-foreground">{truck.name}</p>
                <p className={`text-xs font-medium mt-0.5 ${truck.is_active ? 'text-success' : 'text-muted-foreground'}`}>
                  {truck.is_active ? 'Active' : 'Inactive'}
                </p>
                <p className={`text-xs mt-1 flex items-center justify-center gap-1 ${truck.discord_channel_id ? 'text-success' : 'text-warning'}`}>
                  {truck.discord_channel_id
                    ? <><CheckCircle2 className="w-3 h-3" /> Discord linked</>
                    : <><AlertTriangle className="w-3 h-3" /> No channel</>
                  }
                </p>
              </div>
              <div className="flex items-center gap-2 pt-1">
                <button
                  onClick={() => setEditTarget(truck)}
                  className="p-1.5 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                  title="Edit"
                >
                  <Pencil className="w-3.5 h-3.5" />
                </button>
                {truck.is_active ? (
                  <button
                    onClick={() => handleDeactivate(truck)}
                    className="text-xs font-medium text-danger hover:bg-danger/10 px-2 py-1 rounded-lg transition-colors"
                  >
                    Deactivate
                  </button>
                ) : (
                  <button
                    onClick={() => handleReactivate(truck)}
                    className="text-xs font-medium text-success hover:bg-success/10 px-2 py-1 rounded-lg transition-colors"
                  >
                    Reactivate
                  </button>
                )}
              </div>
            </div>
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// System Tab
// ---------------------------------------------------------------------------

function SystemTab() {
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
      setError(err?.response?.data?.detail ?? 'Something went wrong.');
    } finally {
      setPruning(false);
    }
  };

  return (
    <div className="space-y-6 max-w-lg">
      <ConfirmDialog {...sysConfirmState} onCancel={sysCancelConfirm} />
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
