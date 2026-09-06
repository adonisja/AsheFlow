import { errorText } from '../utils/errorText';
import React, { useState, useEffect, useMemo } from 'react';
import Select from 'react-select';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';
import type { Employee } from '../api/types';
import {
  getRelationships, createRelationship, deleteRelationship,
  type EmployeeRelationship
} from '../api/preferences';
import ErrorBanner from '../components/ui/ErrorBanner';
import ConfirmDialog from '../components/ui/ConfirmDialog';
import { useConfirm } from '../hooks/useConfirm';
import { Heart, ShieldOff, X, ArrowLeftRight, BarChart2, AlertTriangle, Users, HelpCircle, type LucideIcon } from 'lucide-react';
import SettingsHelpDrawer from '../components/ui/SettingsHelpDrawer';
import { getLocalYMD } from '../utils/date';

const selectStyles = {
  control: (base: any, state: any) => ({
    ...base,
    borderRadius: '0.75rem',
    borderColor: state.isFocused ? 'hsl(243 75% 59%)' : 'hsl(220 13% 91%)',
    boxShadow: state.isFocused ? '0 0 0 2px hsl(243 75% 59% / 0.15)' : 'none',
    padding: '2px 4px',
    fontSize: '0.875rem',
    '&:hover': { borderColor: 'hsl(243 75% 59%)' },
  }),
  option: (base: any, state: any) => ({
    ...base,
    fontSize: '0.875rem',
    backgroundColor: state.isSelected ? 'hsl(243 75% 59%)' : state.isFocused ? 'hsl(243 100% 97%)' : 'white',
    color: state.isSelected ? 'white' : 'hsl(224 30% 12%)',
  }),
  groupHeading: (base: any) => ({
    ...base,
    fontSize: '0.75rem',
    fontWeight: '600',
    color: 'hsl(220 9% 46%)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  }),
  singleValue: (base: any) => ({ ...base, color: 'hsl(224 30% 12%)' }),
  placeholder: (base: any) => ({ ...base }),
};

// ---------------------------------------------------------------------------
// Admin Analytics View
// ---------------------------------------------------------------------------

const FIELD_ROLES = ['driver', 'walker', 'trainer'];

function PreferenceAnalytics() {
  const [rels, setRels]   = useState<EmployeeRelationship[]>([]);
  const [emps, setEmps]   = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [matrixTab, setMatrixTab] = useState<'fav' | 'ban'>('fav');

  useEffect(() => {
    Promise.allSettled([
      axiosClient.get('/employee-relationships/').then(r => setRels(r.data)),
      axiosClient.get('/employees/?limit=500').then(r => setEmps(r.data)),
    ]).finally(() => setLoading(false));
  }, []);

  const empMap = useMemo(() => Object.fromEntries(emps.map(e => [e.id, e])), [emps]);

  /* ADR-361 — the admin aggregate endpoint returns dispatch separations too.
     They share a table with bans and are NOT bans: nobody asserted them about
     anybody, and surfacing one here would report a dispatcher's decision as a
     statement two employees made about each other. Everything on this page
     counts from `prefs`, never from the raw rows. */
  const prefs = useMemo(() => rels.filter(r => r.relationship_type !== 'sep'), [rels]);
  const favs = useMemo(() => prefs.filter(r => r.relationship_type === 'fav'), [prefs]);
  const bans = useMemo(() => prefs.filter(r => r.relationship_type === 'ban'), [prefs]);

  // KPIs
  const fieldStaff = useMemo(() => emps.filter(e => FIELD_ROLES.includes(e.role)), [emps]);
  const staffWithPrefs = useMemo(() => new Set(prefs.map(r => r.employee_id)).size, [prefs]);
  const coveragePct = fieldStaff.length > 0 ? Math.round((staffWithPrefs / fieldStaff.length) * 100) : 0;

  // Mutual bans
  const mutualBans = useMemo(() => {
    const banSet = new Set(bans.map(r => `${r.employee_id}:${r.target_employee_id}`));
    const seen = new Set<string>();
    const pairs: { a: string; b: string }[] = [];
    for (const r of bans) {
      const reverse = `${r.target_employee_id}:${r.employee_id}`;
      const key = [r.employee_id, r.target_employee_id].sort().join(':');
      if (banSet.has(reverse) && !seen.has(key)) {
        seen.add(key);
        pairs.push({ a: r.employee_id, b: r.target_employee_id });
      }
    }
    return pairs;
  }, [bans]);

  // Role interaction matrix
  const roles = ['driver', 'walker', 'trainer'];
  const matrix = useMemo(() => {
    const m: Record<string, Record<string, { favs: number; bans: number }>> = {};
    for (const src of roles) {
      m[src] = {};
      for (const tgt of roles) m[src][tgt] = { favs: 0, bans: 0 };
    }
    // `prefs`, not `rels`: the else-branch below counts anything that is not a
    // fav as a ban, so a separation would land in the ban column.
    for (const r of prefs) {
      const src = empMap[r.employee_id]?.role;
      const tgt = empMap[r.target_employee_id]?.role;
      if (src && tgt && m[src]?.[tgt]) {
        if (r.relationship_type === 'fav') m[src][tgt].favs++;
        else m[src][tgt].bans++;
      }
    }
    return m;
  }, [prefs, empMap]);

  // Most favoured / most banned
  const favCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of favs) c[r.target_employee_id] = (c[r.target_employee_id] || 0) + 1;
    return Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 10);
  }, [favs]);

  const banCounts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of bans) c[r.target_employee_id] = (c[r.target_employee_id] || 0) + 1;
    return Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 10);
  }, [bans]);

  const isMutualBan = (id: string) => mutualBans.some(p => p.a === id || p.b === id);

  const empLabel = (id: string) => {
    const e = empMap[id];
    return e ? `${e.name} (${e.role})` : id;
  };

  const matrixMax = useMemo(() => {
    let max = 0;
    for (const src of roles) for (const tgt of roles) {
      const v = matrixTab === 'fav' ? matrix[src]?.[tgt]?.favs : matrix[src]?.[tgt]?.bans;
      if (v > max) max = v;
    }
    return max || 1;
  }, [matrix, matrixTab]);

  if (loading) {
    return (
      <div className="flex h-60 items-center justify-center">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-slide-up">
      {/* Header */}
      <div>
        <h1 className="page-title flex items-center gap-2">
          <BarChart2 className="w-5 h-5 text-primary" /> Preference Analytics
        </h1>
        <p className="text-subtle mt-1">System-wide fav and ban patterns across all field staff.</p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'Total Favs',       value: favs.length,      color: 'text-success' },
          { label: 'Total Bans',       value: bans.length,      color: 'text-danger'  },
          { label: 'Staff Coverage',   value: `${coveragePct}%`, color: coveragePct >= 80 ? 'text-success' : 'text-warning' },
          { label: 'Mutual Conflicts', value: mutualBans.length, color: mutualBans.length > 0 ? 'text-danger' : 'text-subtle' },
        ].map(stat => (
          <div key={stat.label} className="card-elevated">
            <p className="text-xs text-muted-foreground uppercase tracking-wider">{stat.label}</p>
            <p className={`text-2xl font-bold mt-1 ${stat.color}`}>{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Role Interaction Matrix */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <Users className="w-5 h-5 text-primary" />
          <h2 className="text-base font-semibold text-foreground">Role Interaction Matrix</h2>
          <div className="ml-auto flex items-center gap-1 bg-accent rounded-lg p-1 text-xs">
            {(['fav', 'ban'] as const).map(t => (
              <button
                key={t}
                onClick={() => setMatrixTab(t)}
                className={`px-3 py-1 rounded-md font-medium capitalize transition-colors ${matrixTab === t ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
              >
                {t === 'fav' ? 'Favs' : 'Bans'}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-subtle mb-4">Row = who set the preference · Column = who it targets</p>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className="pb-2 pr-4 text-left text-xs text-muted-foreground uppercase tracking-wider w-24">From ↓ To →</th>
                {roles.map(tgt => (
                  <th key={tgt} className="pb-2 px-4 text-center text-xs text-muted-foreground uppercase tracking-wider capitalize">{tgt}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {roles.map(src => (
                <tr key={src}>
                  <td className="py-3 pr-4 text-xs font-semibold text-foreground capitalize">{src}</td>
                  {roles.map(tgt => {
                    const val = matrixTab === 'fav' ? matrix[src]?.[tgt]?.favs : matrix[src]?.[tgt]?.bans;
                    const intensity = val / matrixMax;
                    const bg = matrixTab === 'fav'
                      ? `rgba(34,197,94,${intensity * 0.35})`
                      : `rgba(239,68,68,${intensity * 0.35})`;
                    return (
                      <td key={tgt} className="py-3 px-4 text-center">
                        <span
                          className="inline-block w-12 h-8 leading-8 rounded-lg text-sm font-bold text-foreground"
                          style={{ background: val > 0 ? bg : 'transparent' }}
                        >
                          {val}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Most Favoured + Most Banned side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Most Favoured */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <Heart className="w-5 h-5 text-success" />
            <h2 className="text-base font-semibold text-foreground">Most Favoured</h2>
          </div>
          {favCounts.length === 0 ? (
            <p className="text-sm text-subtle text-center py-6">No favs recorded.</p>
          ) : (
            <div className="space-y-1">
              {favCounts.map(([id, count], i) => (
                <div key={id} className="flex items-center gap-3 px-3 py-2.5 rounded-xl border border-border">
                  <span className="text-xs text-subtle w-5 text-right shrink-0">#{i + 1}</span>
                  <span className="flex-1 text-sm font-medium text-foreground truncate">{empLabel(id)}</span>
                  <span className="text-sm font-bold text-success shrink-0">{count} ★</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Most Banned */}
        <div className="card">
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <ShieldOff className="w-5 h-5 text-danger" />
            <h2 className="text-base font-semibold text-foreground">Most Banned</h2>
          </div>
          {banCounts.length === 0 ? (
            <p className="text-sm text-subtle text-center py-6">No bans recorded.</p>
          ) : (
            <div className="space-y-1">
              {banCounts.map(([id, count], i) => {
                const mutual = isMutualBan(id);
                return (
                  <div key={id} className={`flex items-center gap-3 px-3 py-2.5 rounded-xl border ${mutual ? 'border-danger/40' : 'border-border'}`}>
                    <span className="text-xs text-subtle w-5 text-right shrink-0">#{i + 1}</span>
                    <span className="flex-1 text-sm font-medium text-foreground truncate">{empLabel(id)}</span>
                    {mutual && <span className="text-xs font-bold text-danger bg-danger/10 px-1.5 py-0.5 rounded shrink-0">mutual</span>}
                    <span className="text-sm font-bold text-danger shrink-0">{count} ✕</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Mutual Conflicts */}
      <div className="card">
        <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
          <AlertTriangle className="w-5 h-5 text-danger" />
          <h2 className="text-base font-semibold text-foreground">Mutual Conflicts</h2>
          <span className="ml-auto text-xs text-subtle">Hard dispatch constraints: both parties ban each other</span>
        </div>
        {mutualBans.length === 0 ? (
          <div className="text-center py-8 opacity-60">
            <AlertTriangle className="w-10 h-10 mb-3 text-success mx-auto" />
            <p className="text-sm font-medium">No mutual conflicts.</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {mutualBans.map(({ a, b }) => (
              <div key={`${a}:${b}`} className="py-3 flex items-center justify-between gap-4">
                <span className="text-sm font-medium text-foreground">{empLabel(a)}</span>
                <span className="text-xs font-bold text-danger px-2 py-0.5 rounded bg-danger/10">↔ mutual ban</span>
                <span className="text-sm font-medium text-foreground text-right">{empLabel(b)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field staff preference page
// ---------------------------------------------------------------------------
// Rate Team (ADR-201) — peer ratings: rate each teammate on your truck today.
// ---------------------------------------------------------------------------
function RateTeamSection({ myId }: { myId: string }) {
  const today = getLocalYMD();
  const [crew, setCrew] = useState<{ id: string; name: string; role: string }[]>([]);
  const [given, setGiven] = useState<Record<string, { stars: number; comment: string | null }>>({});
  const [draft, setDraft] = useState<Record<string, { stars: number; comment: string }>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notReady, setNotReady] = useState<string | null>(null);

  const load = async () => {
    try {
      const [crewRes, mineRes] = await Promise.all([
        axiosClient.get(`/field-ops/crew/${myId}`),
        axiosClient.get(`/field-ops/rating/by/${myId}`, { params: { target_date: today } }),
      ]);
      setCrew((crewRes.data ?? []).filter((m: any) => m.id !== myId));
      const g: Record<string, { stars: number; comment: string | null }> = {};
      for (const r of (mineRes.data ?? [])) g[r.ratee_id] = { stars: r.stars, comment: r.comment };
      setGiven(g);
    } catch {
      setCrew([]);
    }
  };
  useEffect(() => { if (myId) load(); }, [myId]);

  const submit = async (rateeId: string) => {
    const d = draft[rateeId];
    if (!d || !d.stars) { setErr('Pick a star rating first.'); return; }
    setBusy(rateeId); setErr(null); setNotReady(null);
    try {
      await axiosClient.post('/field-ops/rating', {
        ratee_id: rateeId, date: today, stars: d.stars, comment: d.comment || null,
      });
      await load();
    } catch (e: unknown) {
      const msg = errorText(e, 'Could not submit rating.');
      // The window-not-open / not-departed case is informational, not an error.
      if (/depart|window/i.test(msg)) setNotReady(msg); else setErr(msg);
    } finally { setBusy(null); }
  };

  if (!crew.length) {
    return (
      <Section icon={Users} title="Rate Team" iconColor="text-primary">
        <p className="text-sm text-subtle">No teammates on your truck today to rate.</p>
      </Section>
    );
  }

  return (
    <Section icon={Users} title="Rate Team" iconColor="text-primary">
      <p className="text-sm text-subtle mb-3">
        Rate each teammate on your truck for today. One rating per person; ratings open once the
        truck has departed. Unrated teammates aren't affected.
      </p>
      {err && <p className="text-xs text-danger mb-2">{err}</p>}
      {notReady && <p className="text-xs text-warning mb-2">{notReady}</p>}
      <div className="divide-y divide-border">
        {crew.map(m => {
          const done = given[m.id];
          const d = draft[m.id] ?? { stars: 0, comment: '' };
          return (
            <div key={m.id} className="py-3">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">{m.name}</p>
                  <p className="text-xs text-subtle capitalize">{m.role}</p>
                </div>
                {done ? (
                  <span className="text-xs text-success font-semibold shrink-0">Rated {done.stars}★</span>
                ) : (
                  <div className="flex items-center gap-1 shrink-0">
                    {[1, 2, 3, 4, 5].map(n => (
                      <button
                        key={n}
                        onClick={() => setDraft(p => ({ ...p, [m.id]: { ...d, stars: n } }))}
                        className={`text-lg leading-none ${n <= d.stars ? 'text-amber-500' : 'text-border'}`}
                        aria-label={`${n} star`}
                      >★</button>
                    ))}
                  </div>
                )}
              </div>
              {!done && (
                <div className="mt-2 flex gap-2">
                  <input
                    value={d.comment}
                    onChange={e => setDraft(p => ({ ...p, [m.id]: { ...d, comment: e.target.value } }))}
                    placeholder="Optional comment"
                    className="flex-1 p-2 rounded-lg border border-border bg-background text-xs"
                  />
                  <button
                    onClick={() => submit(m.id)}
                    disabled={busy === m.id || !d.stars}
                    className="text-xs font-semibold text-white bg-primary rounded-lg px-3 py-1 disabled:opacity-50"
                  >
                    {busy === m.id ? '…' : 'Submit'}
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
const Preferences = () => {
  const { groups = [] } = useAuth();
  const isAdmin = groups.includes('admin');
  const isTrainee = groups.includes('trainee');
  const canFavBan = groups.some(r => ['driver', 'walker', 'trainer'].includes(r));
  const canReassign = groups.some(r => ['walker', 'trainer'].includes(r));

  const { confirmState, confirm, cancelConfirm } = useConfirm();

  const [myId, setMyId] = useState<string>('');
  const [employees, setEmployees] = useState<any[]>([]);
  const [helpKey, setHelpKey] = useState<string | null>(null);
  const [relationships, setRelationships] = useState<EmployeeRelationship[]>([]);
  const [targetFavId, setTargetFavId] = useState('');
  const [targetBanId, setTargetBanId] = useState('');
  const [loadError, setLoadError] = useState<string | null>(null);

  // Truck reassignment — today-only, walker/trainer only
  const [changeRequests, setChangeRequests] = useState<any[]>([]);
  const [changeRequestReason, setChangeRequestReason] = useState('');
  const [changeRequestError, setChangeRequestError] = useState('');

  useEffect(() => {
    if (isAdmin) return;
    axiosClient.get('/employees/me').then(res => setMyId(res.data.id)).catch((e) => { console.error('Failed to load employee identity:', e); });
  }, [isAdmin]);

  useEffect(() => {
    if (isAdmin) return;
    axiosClient.get('/employees/')
      .then(res => {
        const sorted = res.data.sort((a: any, b: any) =>
          (a.first_name || a.name || '').localeCompare(b.first_name || b.name || '')
        );
        setEmployees(sorted);
      })
      .catch(() => setLoadError('Failed to load employee data.'));
  }, [isAdmin]);

  const loadPreferences = async (id: string) => {
    try {
      const rels = await getRelationships(id);
      setRelationships(rels);
    } catch { setLoadError('Failed to load preferences.'); }
  };

  const loadChangeRequests = async (id: string) => {
    try {
      const res = await axiosClient.get(`/assignment-change-requests/employee/${id}`);
      setChangeRequests(res.data);
    } catch { setLoadError('Failed to load change requests.'); }
  };

  useEffect(() => {
    if (myId) {
      loadPreferences(myId);
      loadChangeRequests(myId);
    } else {
      setRelationships([]);
    }
  }, [myId]);

  if (isAdmin) return <PreferenceAnalytics />;

  const today = getLocalYMD();

  const handleSubmitChangeRequest = async () => {
    if (!myId) return;
    setChangeRequestError('');
    try {
      await axiosClient.post('/assignment-change-requests/', {
        employee_id: myId,
        requested_date: today,
        reason: changeRequestReason || undefined,
      });
      setChangeRequestReason('');
      loadChangeRequests(myId);
    } catch (err: unknown) {
      setChangeRequestError(errorText(err, 'Failed to submit request.'));
    }
  };

  const handleCancelChangeRequest = async (id: string) => {
    const ok = await confirm({
      title: 'Cancel Reassignment Request',
      message: 'Are you sure you want to cancel this request? This cannot be undone.',
      confirmLabel: 'Yes, Cancel It',
      variant: 'warning',
    });
    if (!ok) return;
    try {
      await axiosClient.delete(`/assignment-change-requests/${id}`);
      loadChangeRequests(myId);
    } catch (err: unknown) {
      alert(errorText(err, 'Failed to cancel request.'));
    }
  };

  const handleAddFav = async () => { if (!myId || !targetFavId) return; await createRelationship(myId, targetFavId, 'fav'); loadPreferences(myId); setTargetFavId(''); };
  const handleAddBan = async () => { if (!myId || !targetBanId) return; await createRelationship(myId, targetBanId, 'ban'); loadPreferences(myId); setTargetBanId(''); };
  const handleDeleteRelationship = async (item: any) => {
    const name = getEmpName(item.target_employee_id);
    const ok = await confirm({
      title: 'Remove Preference',
      message: `Remove ${name} from your list?`,
      confirmLabel: 'Remove',
      variant: 'danger',
    });
    if (!ok) return;
    await deleteRelationship(item.id);
    loadPreferences(myId);
  };

  const getEmpName = (id: string) => {
    const emp = employees.find(e => e.id === id);
    return emp ? `${emp.first_name || emp.name} (${emp.role})` : id;
  };

  const EXEMPT_ROLES = ['management', 'admin', 'dispatch', 'trainee'];

  /** Mirror of FAV_LIMITS in backend/app/routers/employee_relationships.py
   *  (ADR-353). HAND-MAINTAINED — there is no codegen, so a change to the server
   *  table must be repeated here or the UI will promise slots the API refuses.
   *
   *  A missing pair means ZERO, matching the server's `.get(..., 0)` on both
   *  levels. The gaps are deliberate: driver-driver and captain-captain are one
   *  per truck, and walker-trainer rarely affect each other's day. */
  const FAV_LIMITS: Record<string, Record<string, number>> = {
    driver:  { driver: 0, captain: 2, trainer: 1, walker: 2 },
    captain: { driver: 2, captain: 0, trainer: 1, walker: 2 },
    trainer: { driver: 1, captain: 1, walker: 1 },
    walker:  { driver: 2, captain: 2, walker: 1 },
  };
  /** Bans are global, not per-role — 2 total, matching the server. */
  const BAN_LIMIT = 2;

  const getGroupedOptions = (excludeId?: string) => {
    const currentRole = employees.find(e => e.id === excludeId)?.role;
    let valid = excludeId ? employees.filter(e => e.id !== excludeId) : employees;
    valid = valid.filter(e => !EXEMPT_ROLES.includes(e.role));
    if (currentRole === 'driver') valid = valid.filter(e => e.role !== 'driver');
    const roles = Array.from(new Set(valid.map(e => e.role))).sort();
    return roles.map(role => ({
      label: role.charAt(0).toUpperCase() + role.slice(1) + 's',
      options: valid.filter(e => e.role === role).map(e => ({
        value: e.id, label: `${e.first_name || e.name} (${e.role})`
      }))
    }));
  };

  /** Group headings that show the cap for THIS viewer's role against each target
   *  role, e.g. "Drivers — 1 of 2 used". Previously the only signal that a limit
   *  existed was a 409 after pressing Add. */
  /** Remaining favourite slots per target role, for the summary line under the
   *  picker. The group headings inside the menu only exist once it is OPEN —
   *  the resting state of the page is a closed control, which is where the caps
   *  need to be readable. */
  const favSlotSummary = (excludeId?: string) => {
    const myRole = employees.find(e => e.id === excludeId)?.role;
    const caps = FAV_LIMITS[myRole ?? ''] ?? {};
    return Object.entries(caps)
      .filter(([, cap]) => cap > 0)
      .map(([role, cap]) => {
        const used = favs.filter(f =>
          employees.find(e => e.id === f.target_employee_id)?.role === role).length;
        return { role, used, cap, full: used >= cap };
      });
  };

  /** Role-specific help lines, DERIVED from FAV_LIMITS rather than written out.
   *  A generic entry has to describe every role at once, which is the paragraph
   *  a reader has to work out does not apply to them. Deriving means the help
   *  cannot drift from the caps the picker enforces, or from the server. */
  const favHelpOverride = (excludeId?: string) => {
    const myRole = employees.find(e => e.id === excludeId)?.role;
    if (!myRole || !FAV_LIMITS[myRole]) return undefined;

    const plural = (role: string, n: number) => `${role}${n === 1 ? '' : 's'}`;
    const allRoles = Object.keys(FAV_LIMITS);
    const capFor = (target: string) => FAV_LIMITS[myRole]?.[target] ?? 0;
    const allowed = allRoles.filter(r => capFor(r) > 0).map(r => [r, capFor(r)] as const);
    const barred  = allRoles.filter(r => capFor(r) === 0);

    return {
      favorites: {
        detail: (
          <>
            <p>
              Favorites raise the score of a pairing when dispatch runs. A
              favorite is a strong nudge rather than a rule.
            </p>
            <p className="font-semibold text-foreground">Your limits</p>
            <p>As a {myRole}, you may favor:</p>
            <ul className="mt-1.5 space-y-1">
              {allowed.map(([role, cap]) => (
                <li key={role}>
                  {cap} {plural(role, cap)}
                </li>
              ))}
            </ul>
            <p className="mt-2">
              These are also listed above each group in the picker, with how many
              you have used.
            </p>
          </>
        ),
        note: (
          <>
            {barred.length > 0 && (
              <p>
                A {myRole} cannot favor{' '}
                {barred.map((role, i) => (
                  <span key={role}>
                    {i > 0 ? ' or ' : ''}
                    {role === myRole ? `another ${role}` : `a ${role}`}
                  </span>
                ))}
                , so that group is not offered.
              </p>
            )}
            <p className={barred.length > 0 ? 'mt-1.5' : ''}>
              Existing favorites above a limit are kept; the limit only gates new
              ones.
            </p>
          </>
        ),
      },
      blocked: {
        detail: (
          <>
            <p>
              A block is honoured absolutely. Dispatch will not place you on the
              same truck, regardless of how well the pairing otherwise scores.
            </p>
            <p className="font-semibold text-foreground">Two blocks, total</p>
            <p>
              Unlike favorites, this limit is not per role. You may hold{' '}
              <span className="text-danger font-semibold">
                two blocks in total
              </span>
              , across everyone. You have used {bans.length} of {BAN_LIMIT}.
            </p>
          </>
        ),
      },
    };
  };

  const getFavOptions = (excludeId?: string) => {
    const myRole = employees.find(e => e.id === excludeId)?.role;
    return getGroupedOptions(excludeId)
      .map(g => {
        const targetRole = g.label.slice(0, -1).toLowerCase();
        const cap  = FAV_LIMITS[myRole ?? '']?.[targetRole] ?? 0;
        const used = favs.filter(f =>
          employees.find(e => e.id === f.target_employee_id)?.role === targetRole).length;
        return { ...g, targetRole, cap, used };
      })
      // A cap of 0 is PERMANENT for this role pair — a walker will never be able
      // to favourite a trainer — so there is no rule to teach by showing it. Drop
      // the group rather than making the user scroll past people they can never
      // pick. A group that is merely FULL is different: those options stay,
      // disabled, because removing one favourite makes them selectable again.
      .filter(g => g.cap > 0)
      .map(g => ({
        label: `${g.label} · ${g.used} of ${g.cap} used`,
        options: g.options.map(o => ({ ...o, isDisabled: g.used >= g.cap })),
      }));
  };

  const favs = relationships.filter(r => r.relationship_type === 'fav');
  const bans = relationships.filter(r => r.relationship_type === 'ban');

  const statusBadge = (status: string) => {
    if (status === 'pending') return 'badge-warning';
    if (status === 'approved') return 'badge-success';
    if (status === 'rejected') return 'badge-danger';
    return 'badge bg-accent text-muted-foreground';
  };

  // For the reassignment section, only show pending/today's requests
  const hasPendingToday = changeRequests.some(r => r.requested_date === today && r.status === 'pending');
  const recentRequests = changeRequests.slice(0, 5);

  return (
    <div className="space-y-6 animate-slide-up">
      <ConfirmDialog {...confirmState} onCancel={cancelConfirm} />
      <h1 className="page-title">Preferences</h1>

      <ErrorBanner message={loadError} />


      {myId && (
        <div className="space-y-6">
          {/* Rate Team — peer ratings for today's truck crew (ADR-201) */}
          <RateTeamSection myId={myId} />

          {/* Truck Reassignment — walker/trainer only, today-only */}
          {canReassign && (
            <Section icon={ArrowLeftRight} title="Truck Reassignment Request" iconColor="text-warning">
              <p className="text-sm text-subtle mb-4">
                Request to be moved to a different truck for <strong>today</strong>. You must be currently assigned to submit. Dispatch will review.
              </p>
              {!hasPendingToday ? (
                <div className="flex flex-col gap-3 mb-4">
                  <input
                    type="text"
                    value={changeRequestReason}
                    onChange={(e) => setChangeRequestReason(e.target.value)}
                    placeholder="Reason (optional)"
                    className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                  />
                  {changeRequestError && (
                    <p className="text-xs text-danger">{changeRequestError}</p>
                  )}
                  <button
                    onClick={handleSubmitChangeRequest}
                    className="btn-primary text-xs self-start"
                  >
                    Request Reassignment for Today
                  </button>
                </div>
              ) : (
                <p className="text-sm text-warning mb-4">You have a pending reassignment request for today.</p>
              )}
              <ul className="space-y-2">
                {recentRequests.length === 0 && (
                  <li className="text-subtle py-4 text-center text-sm">No reassignment requests yet.</li>
                )}
                {recentRequests.map((req) => (
                  <li key={req.id} className="flex items-center justify-between p-3 rounded-xl bg-accent/50">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-sm font-medium text-foreground">{req.requested_date}</span>
                      {req.reason && <span className="text-xs text-subtle">{req.reason}</span>}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={statusBadge(req.status)}>{req.status}</span>
                      {req.status === 'pending' && (
                        <button
                          onClick={() => handleCancelChangeRequest(req.id)}
                          className="btn-ghost text-muted-foreground p-1.5 hover:text-danger"
                          title="Cancel request"
                        >
                          <X className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {/* Favorites — driver/walker/trainer only (not trainee) */}
          {canFavBan && (
            <Section icon={Heart} title="Favorites" iconColor="text-success"
                     helpKey="favorites" onHelp={setHelpKey}>
              <div className="flex gap-3 mb-4">
                <div className="flex-1">
                  {(() => {
                    const favOpts = getFavOptions(myId);
                    const favValue = favOpts.flatMap(g => g.options).find(o => o.value === targetFavId) || null;
                    return (
                      <Select
                        options={favOpts}
                        value={favValue}
                        onChange={(s) => setTargetFavId(s?.value || '')}
                        placeholder="Search and select to add..."
                        isClearable
                        isSearchable
                        styles={selectStyles}
                      />
                    );
                  })()}
                </div>
                <button onClick={handleAddFav} className="btn-primary text-xs">Add</button>
              </div>
              {favSlotSummary(myId).length > 0 && (
                <p className="text-xs text-muted-foreground mb-4 flex flex-wrap gap-x-3 gap-y-1">
                  {favSlotSummary(myId).map(s => (
                    <span key={s.role} className={s.full ? 'text-warning font-medium' : ''}>
                      {s.used}/{s.cap} {s.role}{s.cap === 1 ? '' : 's'}
                    </span>
                  ))}
                </p>
              )}
              <ItemList items={favs} getLabel={(f) => getEmpName(f.target_employee_id)} onDelete={handleDeleteRelationship} emptyText="No favorites yet." />
            </Section>
          )}

          {/* Blocked — driver/walker/trainer only (not trainee) */}
          {canFavBan && (
            <Section icon={ShieldOff} title="Blocked" iconColor="text-danger"
                     helpKey="blocked" onHelp={setHelpKey}>
              <div className="flex gap-3 mb-4">
                <div className="flex-1">
                  {(() => {
                    const banOpts = getGroupedOptions(myId);
                    const banValue = banOpts.flatMap(g => g.options).find(o => o.value === targetBanId) || null;
                    return (
                      <Select
                        options={banOpts}
                        value={banValue}
                        onChange={(s) => setTargetBanId(s?.value || '')}
                        placeholder={bans.length >= BAN_LIMIT
                          ? `Block limit reached (${BAN_LIMIT} of ${BAN_LIMIT})`
                          : 'Search and select to block...'}
                        isDisabled={bans.length >= BAN_LIMIT}
                        isClearable
                        isSearchable
                        styles={selectStyles}
                      />
                    );
                  })()}
                </div>
                <button onClick={handleAddBan} className="btn-primary text-xs">Add</button>
              </div>
              <p className={`text-xs mb-4 ${bans.length >= BAN_LIMIT ? 'text-warning font-medium' : 'text-muted-foreground'}`}>
                {bans.length} of {BAN_LIMIT} blocks used
              </p>
              <ItemList items={bans} getLabel={(b) => getEmpName(b.target_employee_id)} onDelete={handleDeleteRelationship} emptyText="No blocks yet." />
            </Section>
          )}

          {/* Trainees see a placeholder explaining what they'll unlock */}
          {isTrainee && (
            <div className="card text-center py-8">
              <p className="text-sm text-subtle">Dispatch preferences (favorites & blocks) become available after graduating from the training program.</p>
            </div>
          )}

        </div>
      )}

      <SettingsHelpDrawer
        fieldKey={helpKey}
        onClose={() => setHelpKey(null)}
        overrides={favHelpOverride(myId)}
      />
    </div>
  );
};

function Section({ icon: Icon, title, iconColor, children, helpKey, onHelp }: { icon: LucideIcon; title: string; iconColor: string; children: React.ReactNode; helpKey?: string; onHelp?: (k: string) => void }) {
  return (
    <div className="card">
      <div className="flex items-center gap-3 mb-5">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-accent">
          <Icon className={`w-4 h-4 ${iconColor}`} />
        </div>
        <h2 className="section-title">{title}</h2>
        {helpKey && onHelp && (
          <button
            type="button"
            onClick={() => onHelp(helpKey)}
            aria-label={`What are ${title.toLowerCase()}?`}
            className="text-muted-foreground/60 hover:text-primary transition-colors"
          >
            <HelpCircle className="w-4 h-4" />
          </button>
        )}
      </div>
      {children}
    </div>
  );
}

function ItemList({ items, getLabel, onDelete, emptyText }: { items: any[]; getLabel: (item: any) => string; onDelete: (item: any) => void; emptyText: string }) {
  return (
    <ul className="space-y-2">
      {items.map(item => (
        <li key={item.id} className="flex items-center justify-between p-3 rounded-xl bg-accent/50">
          <span className="text-sm font-medium text-foreground">{getLabel(item)}</span>
          <button onClick={() => onDelete(item)} className="btn-ghost text-muted-foreground p-1.5 hover:text-danger"><X className="w-4 h-4" /></button>
        </li>
      ))}
      {items.length === 0 && <li className="text-subtle py-4 text-center">{emptyText}</li>}
    </ul>
  );
}

export default Preferences;
