import React, { useCallback, useEffect, useState } from 'react';
import { ShieldCheck, UserPlus, RefreshCw, KeyRound } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import SectionHeader from '../../components/ui/SectionHeader';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { SkeletonCard } from '../../components/ui/Skeleton';
import { errorText } from '../../utils/errorText';
import { useConfirm } from '../../hooks/useConfirm';
import ConfirmDialog from '../../components/ui/ConfirmDialog';

/** Platform staff, and the MFA reset that had no caller (ADR-394, ADR-389).
 *
 *  Two controls that previously existed only as AWS CLI commands in a runbook:
 *
 *  - Creating a second super admin. ADR-389's mitigation for the circular
 *    lockout is "keep two", and that was unaudited, untested, and unavailable to
 *    anyone without AWS credentials.
 *  - `POST /platform/mfa/reset`, which shipped with no UI. It is the only path
 *    by which a locked-out ADMIN can be rescued, because the tenant-scoped
 *    endpoint resolves the CALLER through an Employee row that a super admin
 *    does not have.
 */

interface StaffRow {
  username: string;
  email: string;
  group: string;
  status: string;
}

const GROUPS = [
  { value: 'super_admin', label: 'Super admin',
    hint: 'Full platform access, including creating other staff.' },
  { value: 'platform_support', label: 'Platform support',
    hint: 'Read-only. Can diagnose a tenant issue without changing anything.' },
];

export default function PlatformStaff() {
  const [rows, setRows] = useState<StaffRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [email, setEmail] = useState('');
  const [name, setName] = useState('');
  const [group, setGroup] = useState('super_admin');
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<StaffRow | null>(null);

  const [resetUser, setResetUser] = useState('');
  const [resetting, setResetting] = useState(false);
  const [resetMsg, setResetMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const { confirmState, confirm, cancelConfirm } = useConfirm();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get('/platform/staff');
      setRows(res.data);
    } catch (err) {
      setError(errorText(err, 'Could not load platform staff.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setError(null);
    setCreated(null);
    try {
      const res = await axiosClient.post('/platform/staff', {
        email: email.trim(), name: name.trim(), group,
      });
      setCreated(res.data);
      setEmail(''); setName('');
      await load();
    } catch (err) {
      setError(errorText(err, 'Could not create the account.'));
    } finally {
      setCreating(false);
    }
  };

  const handleReset = async () => {
    const target = resetUser.trim();
    if (!target) return;
    const ok = await confirm({
      title: 'Reset two-factor authentication',
      message: `Clear ${target}'s MFA factor, end every session and forget every remembered device? They will set it up again at their next sign-in.`,
      confirmLabel: 'Reset',
      variant: 'danger',
    });
    if (!ok) return;
    setResetting(true);
    setResetMsg(null);
    try {
      const res = await axiosClient.post('/platform/mfa/reset', { username: target });
      setResetMsg({
        ok: true,
        text: `Cleared. Signed out, ${res.data.devices_forgotten} device(s) forgotten.`,
      });
      setResetUser('');
    } catch (err: any) {
      // 502 means containment ran but did NOT fully complete. The operator must
      // not read it as done -- the account may still be locked out (ADR-392).
      setResetMsg({
        ok: false,
        text: err?.response?.status === 502
          ? 'Did not fully complete. Check the account and try again.'
          : errorText(err, 'Could not reset two-factor authentication.'),
      });
    } finally {
      setResetting(false);
    }
  };

  const superAdmins = rows.filter(r => r.group === 'super_admin');

  return (
    <div className="space-y-6">
      <SectionHeader
        eyebrow="Platform"
        title={
          <span className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-primary" />
            Platform staff
          </span>
        }
        description="Who can administer the platform, and account recovery"
        actions={
          <button onClick={() => void load()} disabled={loading}
                  className="btn-secondary text-sm flex items-center gap-2 disabled:opacity-50">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        }
      />

      <ErrorBanner message={error} />

      {/* A single super admin is a single point of failure: if that
          authenticator is lost, recovery needs raw AWS credentials because the
          account cannot be reset from inside the product (ADR-389). */}
      {!loading && superAdmins.length < 2 && (
        <div className="rounded-lg border border-warning/30 bg-warning/10 p-4">
          <p className="text-sm font-medium">Only one super admin</p>
          <p className="text-sm text-muted-foreground mt-1">
            If that authenticator is lost, recovering it needs AWS credentials.
            Add a second super admin on a different device.
          </p>
        </div>
      )}

      {loading ? <SkeletonCard /> : (
        <div className="card">
          <h3 className="section-title mb-4">Current staff</h3>
          {rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">No platform staff found.</p>
          ) : (
            <ul className="divide-y divide-border">
              {rows.map(r => (
                <li key={`${r.group}:${r.username}`}
                    className="flex items-center justify-between gap-4 py-3 flex-wrap">
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{r.email || r.username}</p>
                    <p className="text-xs text-muted-foreground">{r.username}</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {/* FORCE_CHANGE_PASSWORD means they have never signed in, so
                        they are not yet a working rescuer (ADR-394). */}
                    {r.status === 'FORCE_CHANGE_PASSWORD' && (
                      <span className="text-[10px] uppercase tracking-wide bg-warning/15 text-warning rounded-md px-2 py-0.5">
                        Not signed in yet
                      </span>
                    )}
                    <span className="text-xs bg-accent rounded-md px-2 py-1">
                      {r.group === 'super_admin' ? 'Super admin' : 'Platform support'}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="card">
        <h3 className="section-title mb-1 flex items-center gap-2">
          <UserPlus className="w-4 h-4 text-muted-foreground" /> Add platform staff
        </h3>
        <p className="text-sm text-muted-foreground mb-4">
          They receive a temporary password by email, then set a permanent one and
          add an authenticator app before they can sign in.
        </p>
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="block text-sm font-medium mb-1.5">Email</label>
              <input type="email" required value={email} className="input-field"
                     onChange={e => setEmail(e.target.value)} autoComplete="off" />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1.5">Name</label>
              <input type="text" required maxLength={255} value={name}
                     className="input-field" onChange={e => setName(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium mb-1.5">Role</label>
            <div className="space-y-2">
              {GROUPS.map(g => (
                <label key={g.value}
                       className={`flex items-start gap-3 p-3 rounded-xl border cursor-pointer transition-colors ${
                         group === g.value ? 'border-primary bg-primary/5' : 'border-border hover:bg-accent'
                       }`}>
                  <input type="radio" name="group" value={g.value} className="mt-1"
                         checked={group === g.value}
                         onChange={() => setGroup(g.value)} />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{g.label}</span>
                    <span className="block text-xs text-muted-foreground">{g.hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>
          <button type="submit" disabled={creating}
                  className="btn-primary text-sm disabled:opacity-50">
            {creating ? 'Creating…' : 'Create account'}
          </button>
        </form>

        {created && (
          <div className="mt-4 rounded-lg border border-success/30 bg-success/10 p-4">
            <p className="text-sm font-medium">Created {created.email}</p>
            <p className="text-sm text-muted-foreground mt-1">
              A temporary password has been emailed. They cannot sign in until they
              set a permanent password and add an authenticator app.
            </p>
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="section-title mb-1 flex items-center gap-2">
          <KeyRound className="w-4 h-4 text-muted-foreground" /> Reset two-factor authentication
        </h3>
        <p className="text-sm text-muted-foreground mb-4">
          For an account that has lost its authenticator. Clears the factor, ends
          every session and forgets every remembered device. A privileged account
          must also be removed from its group temporarily before it can sign in
          again. See the lockout runbook.
        </p>
        <div className="flex gap-3 flex-wrap">
          <input type="text" value={resetUser} placeholder="Cognito username"
                 className="input-field flex-1 min-w-[220px]" autoComplete="off"
                 onChange={e => setResetUser(e.target.value)} />
          <button onClick={() => void handleReset()}
                  disabled={resetting || !resetUser.trim()}
                  className="btn-primary text-sm bg-danger hover:bg-danger/90 disabled:opacity-50">
            {resetting ? 'Resetting…' : 'Reset'}
          </button>
        </div>
        {resetMsg && (
          <p className={`text-sm mt-3 ${resetMsg.ok ? 'text-success' : 'text-danger'}`}>
            {resetMsg.text}
          </p>
        )}
      </div>

      <ConfirmDialog {...confirmState} onCancel={cancelConfirm} />
    </div>
  );
}
