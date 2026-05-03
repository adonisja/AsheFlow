import React, { useState, useEffect } from 'react';
import {
  Users, Truck, Plus, Pencil, CheckCircle2, XCircle, AlertTriangle,
  RefreshCw, X, ChevronDown, Settings, Trash2, FileUp,
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
  discord_id: string;
  cognito_sub: string | null;
  role: string;
  is_active: boolean;
  phone_number: string | null;
};

type TruckRecord = {
  id: string;
  name: string;
  is_active: boolean;
  discord_channel_id: number | null;
};

type Tab = 'people' | 'fleet' | 'system';

const ROLES = ['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin'];

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
};

function EmployeeModal({ initial = {}, onSave, onClose, isCreate }: EmployeeFormProps) {
  const [form, setForm] = useState({
    name:         initial.name         ?? '',
    email:        initial.email        ?? '',
    discord_id:   initial.discord_id   ?? '',
    role:         initial.role         ?? 'driver',
    phone_number: initial.phone_number ?? '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError]   = useState('');

  const set = (k: string, v: string) => setForm(f => ({ ...f, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      await onSave(form);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Something went wrong.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-card w-full max-w-md rounded-2xl border border-border shadow-xl animate-slide-up">
        <div className="flex items-center justify-between p-5 border-b border-border">
          <h2 className="font-semibold text-foreground">
            {isCreate ? 'Invite New Employee' : 'Edit Employee'}
          </h2>
          <button onClick={onClose} className="btn-ghost p-1.5"><X className="w-4 h-4" /></button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {error && (
            <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-xl px-3 py-2">
              {error}
            </div>
          )}

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Full Name *</label>
            <input
              required
              value={form.name}
              onChange={e => set('name', e.target.value)}
              className="input w-full"
              placeholder="Jane Smith"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              Email {isCreate && <span className="text-danger">*</span>}
            </label>
            <input
              required={isCreate}
              type="email"
              value={form.email}
              onChange={e => set('email', e.target.value)}
              className="input w-full"
              placeholder="jane@example.com"
            />
            {isCreate && (
              <p className="text-xs text-subtle">An invite email will be sent to this address.</p>
            )}
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Discord ID *</label>
            <input
              required
              value={form.discord_id}
              onChange={e => set('discord_id', e.target.value)}
              className="input w-full"
              placeholder="username#1234 or user ID"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Role *</label>
            <div className="relative">
              <select
                required
                value={form.role}
                onChange={e => set('role', e.target.value)}
                className="input w-full appearance-none pr-8 capitalize"
              >
                {ROLES.map(r => (
                  <option key={r} value={r} className="capitalize">{r}</option>
                ))}
              </select>
              <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Phone (optional)</label>
            <input
              type="tel"
              value={form.phone_number}
              onChange={e => set('phone_number', e.target.value)}
              className="input w-full"
              placeholder="+1 (555) 000-0000"
            />
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="btn-ghost">Cancel</button>
            <button
              type="submit"
              disabled={saving}
              className="btn-primary flex items-center gap-2"
            >
              {saving && <div className="w-3.5 h-3.5 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />}
              {isCreate ? 'Send Invite' : 'Save Changes'}
            </button>
          </div>
        </form>
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
              placeholder="e.g. TRUCK_CHANNEL_REDACTED"
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
  const canImport                     = groups.includes('management') || groups.includes('admin');
  const { confirmState, confirm, cancelConfirm } = useConfirm();

  const [employees, setEmployees]     = useState<Employee[]>([]);
  const [loading, setLoading]         = useState(true);
  const [loadError, setLoadError]     = useState<string | null>(null);
  const [showModal, setShowModal]     = useState(false);
  const [showImport, setShowImport]   = useState(false);
  const [editTarget, setEditTarget]   = useState<Employee | null>(null);
  const [filter, setFilter]           = useState<string>('all');
  const [search, setSearch]           = useState('');
  const [page, setPage]               = useState(0);

  const load = () => {
    setLoading(true);
    setLoadError(null);
    axiosClient.get('/employees/?limit=500')
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

  const visible = employees.filter(e => {
    const matchRole   = filter === 'all' || e.role === filter;
    const matchSearch = !search || e.name.toLowerCase().includes(search.toLowerCase())
      || (e.email ?? '').toLowerCase().includes(search.toLowerCase())
      || (e.discord_id ?? '').toLowerCase().includes(search.toLowerCase());
    return matchRole && matchSearch;
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
        {visible.filter(e => e.is_active).length} active · {visible.filter(e => !e.is_active).length} inactive
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
                  <tr key={emp.id} className={`transition-colors hover:bg-accent/20 ${!emp.is_active ? 'opacity-50' : ''}`}>
                    <td className="px-4 py-3 font-medium text-foreground whitespace-nowrap">{emp.name}</td>
                    <td className="px-4 py-3">
                      <span className={badge(emp.role)}>{emp.role}</span>
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell text-muted-foreground text-xs truncate max-w-[180px]">
                      {emp.email ?? <span className="text-subtle italic">—</span>}
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell font-mono text-xs text-muted-foreground">
                      {emp.discord_id}
                    </td>
                    <td className="px-4 py-3 hidden lg:table-cell text-xs text-muted-foreground">
                      {emp.phone_number ?? <span className="text-subtle italic">—</span>}
                    </td>
                    <td className="px-4 py-3">
                      {emp.is_active ? (
                        <span className="inline-flex items-center gap-1 text-success text-xs font-medium">
                          <CheckCircle2 className="w-3 h-3" /> Active
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-muted-foreground text-xs font-medium">
                          <XCircle className="w-3 h-3" /> Inactive
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-2">
                        <button
                          onClick={() => setEditTarget(emp)}
                          className="p-1.5 rounded-lg hover:bg-accent text-muted-foreground hover:text-foreground transition-colors"
                          title="Edit"
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => handleToggleActive(emp)}
                          className={`text-xs font-medium px-2 py-1 rounded-lg transition-colors ${
                            emp.is_active
                              ? 'text-danger hover:bg-danger/10'
                              : 'text-success hover:bg-success/10'
                          }`}
                        >
                          {emp.is_active ? 'Deactivate' : 'Reactivate'}
                        </button>
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
        />
      )}
      {editTarget && (
        <EmployeeModal
          isCreate={false}
          initial={editTarget}
          onSave={handleEdit}
          onClose={() => setEditTarget(null)}
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
