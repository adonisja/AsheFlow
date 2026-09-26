import { errorText } from '../../utils/errorText';
import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  Building2, Plus, RefreshCw, CheckCircle2, XCircle,
  ChevronDown, ChevronUp, Send, AlertTriangle, ChevronRight,
  ShieldCheck, ShieldAlert, X, UserX,
} from 'lucide-react';
import SelectMenu, { type SelectOption } from '../../components/ui/SelectMenu';
import axiosClient from '../../api/axiosClient';
import SectionHeader from '../../components/ui/SectionHeader';
import StatCard from '../../components/ui/StatCard';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { SkeletonCard } from '../../components/ui/Skeleton';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Current abbreviation and UTC offset for an IANA zone, e.g. "EDT · UTC-4".
 *
 *  COMPUTED, never hardcoded. Half these zones shift twice a year and they do
 *  not shift together: today Denver is MDT (UTC-7) while Phoenix, which does
 *  not observe DST at all, is MST (UTC-7) — and in January they diverge again.
 *  A written-down table is wrong for roughly half the year, silently, in a
 *  field whose whole job is to be unambiguous about time.
 */
function zoneHint(tz: string): string {
  const now = new Date();
  const abbr = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'short' })
    .formatToParts(now).find(p => p.type === 'timeZoneName')?.value ?? '';
  const gmt = new Intl.DateTimeFormat('en-US', { timeZone: tz, timeZoneName: 'shortOffset' })
    .formatToParts(now).find(p => p.type === 'timeZoneName')?.value ?? '';
  // "GMT-4" reads as UTC to anyone scheduling across zones; "GMT" invites the
  // question of whether it means London, which in summer it does not.
  return `${abbr} · ${gmt.replace('GMT', 'UTC')}`;
}

/** The timezones a DSP can operate in, grouped by region.
 *
 *  Shared so the create form and the company detail editor cannot drift apart.
 *  Grouped because a flat list of "America/..." strings makes the reader parse
 *  a path prefix that carries no information once the heading says it.
 */
export const TIMEZONES: SelectOption[] = [
  { value: '_us', label: 'United States', header: true },
  { value: 'America/New_York',    label: 'New York',    hint: zoneHint('America/New_York') },
  { value: 'America/Chicago',     label: 'Chicago',     hint: zoneHint('America/Chicago') },
  { value: 'America/Denver',      label: 'Denver',      hint: zoneHint('America/Denver') },
  { value: 'America/Phoenix',     label: 'Phoenix',     hint: zoneHint('America/Phoenix') },
  { value: 'America/Los_Angeles', label: 'Los Angeles', hint: zoneHint('America/Los_Angeles') },
  { value: '_nc', label: 'Non-contiguous', header: true },
  { value: 'America/Anchorage',   label: 'Anchorage',   hint: zoneHint('America/Anchorage') },
  { value: 'Pacific/Honolulu',    label: 'Honolulu',    hint: zoneHint('Pacific/Honolulu') },
];

interface Company {
  id: string;
  name: string;
  slug: string;
  amazon_dsp_code: string | null;
  timezone: string;
  is_active: boolean;
  created_at: string;
  has_admin: boolean;
  /** ADR-451 D6. The Owner, read from the SERVER. This page is where the Owner
   *  is created, so it is where the existing one has to be visible: it used to
   *  hold the result of its own last bootstrap call in React state, which is
   *  gone on reload, so an operator could not see what they were about to
   *  duplicate. */
  owner: OwnerSummary | null;
  /** ADR-280 — is this tenant's data real? Super admin is the one
   *  cross-tenant surface, so it is the one place this has to show. */
  data_class: 'live' | 'seed' | 'demo';
}

interface OwnerSummary {
  employee_id: string;
  name: string;
  email: string | null;
  account_status: string;
  /** A requested address awaiting confirmation (ADR-451 D4). Shown so the
   *  operator sees a change is in flight rather than wondering why the address
   *  looks stale. */
  pending_email: string | null;
}

/** Company creation, plus the machine client credentials (ADR-364).
 *
 *  `machine_client_secret` is present ONLY in this response. It is never
 *  stored, so this is the one moment it can be copied without a separate
 *  reveal. `machine_client_error` means the company was created but Cognito
 *  provisioning failed — the tenant works, its bot does not, and provisioning
 *  can be retried from the company detail page. */
interface CompanyCreated extends Company {
  machine_client_id?: string | null;
  machine_client_secret?: string | null;
  machine_client_error?: string | null;
}

interface BootstrapResult {
  employee_id: string;
  name: string;
  email: string;
  role: string;
  account_status: string;
  invite_sent: boolean;
}

// ---------------------------------------------------------------------------
// Create company form
// ---------------------------------------------------------------------------

function CreateCompanyForm({
  onCreated,
  onClose,
}: {
  onCreated: (c: Company) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [dspCode, setDspCode] = useState('');
  const [timezone, setTimezone] = useState('America/New_York');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [created, setCreated] = useState<CompanyCreated | null>(null);

  const handleNameChange = (v: string) => {
    setName(v);
    setSlug(v.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const res = await axiosClient.post<CompanyCreated>('/admin/companies/', {
        name: name.trim(),
        slug: slug.trim(),
        amazon_dsp_code: dspCode.trim() || null,
        timezone,
      });
      onCreated(res.data);
      /* ADR-364 — the machine client secret is shown ONCE and never stored, so
         the form stays open until it has been copied. Closing on success (what
         this did before) would discard the only copy, and recovering it means
         a separate reveal action. */
      if (res.data.machine_client_secret) {
        setCreated(res.data);
      } else {
        onClose();
      }
    } catch (err: unknown) {
      setError(errorText(err, 'Failed to create company.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.15 }}
      className="card"
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-sm">
          {created ? 'Company Created' : 'Create New Company'}
        </h3>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>
      {error && <ErrorBanner message={error} className="mb-3" />}

      {/* ADR-364 — shown once. The secret is not stored anywhere, so this panel
          replaces the form rather than sitting under it: a superadmin who
          scrolls past and closes has lost the only copy. */}
      {created ? (
        <div className="space-y-4">
          <p className="text-sm text-foreground">
            <span className="font-medium">{created.name}</span> is ready. Its
            Discord bot signs in with the credentials below.
          </p>

          {created.machine_client_error ? (
            <div className="rounded-lg border border-warning/30 bg-warning/5 px-3 py-2.5">
              <p className="text-xs text-foreground leading-relaxed">
                The company was created, but its bot credentials could not be
                provisioned: {created.machine_client_error} You can retry from
                the company's detail page. Everything else works in the meantime.
              </p>
            </div>
          ) : (
            <>
              <div className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2.5">
                <p className="text-xs text-foreground leading-relaxed">
                  <span className="font-semibold text-danger">Copy the secret now.</span>{' '}
                  It is not stored. If you lose it you can reveal it again from
                  the company's detail page, but it is not shown here twice.
                </p>
              </div>

              {[
                ['COGNITO_M2M_CLIENT_ID', created.machine_client_id],
                ['COGNITO_M2M_CLIENT_SECRET', created.machine_client_secret],
              ].map(([label, value]) => (
                <div key={label as string}>
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    {label}
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="flex-1 text-xs bg-accent rounded-lg px-3 py-2 break-all">
                      {value}
                    </code>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard?.writeText(String(value ?? ''))}
                      className="text-xs px-2.5 py-2 rounded-lg border border-border hover:bg-accent shrink-0"
                    >
                      Copy
                    </button>
                  </div>
                </div>
              ))}

              <p className="text-[11px] text-muted-foreground">
                Paste both into this tenant's bot environment, alongside
                COGNITO_OAUTH_DOMAIN.
              </p>
            </>
          )}

          <button onClick={onClose} className="btn-primary text-sm px-4 py-2">
            Done
          </button>
        </div>
      ) : (
      <form onSubmit={handleSubmit}>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Company Name</label>
            <input
              className="input-field"
              value={name}
              onChange={e => handleNameChange(e.target.value)}
              placeholder="Acme DSP LLC"
              required
              autoFocus
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">
              Slug <span className="text-muted-foreground/60">(auto-derived)</span>
            </label>
            <input
              className="input-field font-mono text-sm"
              value={slug}
              onChange={e => setSlug(e.target.value.toLowerCase())}
              placeholder="acme-dsp"
              required
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">
              Amazon DSP Code <span className="text-muted-foreground/60">(optional)</span>
            </label>
            <input
              className="input-field"
              value={dspCode}
              onChange={e => setDspCode(e.target.value)}
              placeholder="DSPX1234"
            />
          </div>
          <div>
            <label className="block text-xs text-muted-foreground mb-1">Timezone</label>
            {/* House dropdown, not a native <select>: the native one renders
                with the OS palette, so on a dark theme it opened as a white
                panel with a system-blue highlight (the same failure
                CollectionData.tsx documents). */}
            <SelectMenu
              value={timezone}
              options={TIMEZONES}
              placeholder="Select a timezone"
              ariaLabel="Timezone"
              onChange={setTimezone}
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button type="button" onClick={onClose} className="btn-ghost text-sm">
            Cancel
          </button>
          <button type="submit" disabled={saving} className="btn-primary text-sm">
            {saving ? 'Creating…' : 'Create Company'}
          </button>
        </div>
      </form>
      )}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Bootstrap form (inline per company row)
// ---------------------------------------------------------------------------

function BootstrapForm({ companyId, onDone }: { companyId: string; onDone: (r: BootstrapResult) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const res = await axiosClient.post<BootstrapResult>(
        `/admin/companies/${companyId}/bootstrap`,
        { name: name.trim(), email: email.trim() },
      );
      onDone(res.data);
      setOpen(false);
      setName(''); setEmail('');
    } catch (err: unknown) {
      setError(errorText(err, 'Bootstrap failed.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div onClick={e => e.stopPropagation()}>
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 text-xs text-violet-500 hover:text-violet-400 transition-colors font-medium"
      >
        <Send className="w-3.5 h-3.5" />
        Bootstrap Admin
        {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-3 p-3 rounded-xl bg-accent/50 border border-border/50">
              {error && <p className="text-xs text-danger mb-2">{error}</p>}
              <form onSubmit={handleSubmit} className="space-y-2">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Admin Name</label>
                  <input
                    className="input-field text-sm"
                    value={name}
                    onChange={e => setName(e.target.value)}
                    placeholder="Jane Smith"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Admin Email</label>
                  <input
                    type="email"
                    className="input-field text-sm"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    placeholder="jane@acmedsp.com"
                    required
                  />
                </div>
                <div className="flex justify-end gap-2 pt-1">
                  <button type="button" onClick={() => setOpen(false)} className="btn-ghost text-xs">
                    Cancel
                  </button>
                  <button type="submit" disabled={saving} className="btn-primary text-xs">
                    {saving ? 'Sending…' : 'Send Invite'}
                  </button>
                </div>
              </form>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Company row
// ---------------------------------------------------------------------------

function CompanyRow({
  company,
  onToggle,
}: {
  company: Company;
  onToggle: (id: string, active: boolean) => void;
}) {
  const navigate = useNavigate();
  const [bootstrapResult, setBootstrapResult] = useState<BootstrapResult | null>(null);
  const [toggling, setToggling] = useState(false);
  const [resending, setResending] = useState(false);

  /** Re-send the invite when the first email did not go out (ADR-442 D1).
   *
   *  Calls the SAME bootstrap endpoint. It is already idempotent: given an
   *  email that already has an admin row for this company, it reuses that row,
   *  invalidates the prior token and issues a fresh one. A dedicated resend
   *  endpoint would duplicate that and drift from it.
   *
   *  The UI was the whole gap — once a result existed the form was replaced by
   *  a status line, so the message said "Retry to resend" with nothing to
   *  click. */
  const resendInvite = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!bootstrapResult) return;
    setResending(true);
    try {
      const res = await axiosClient.post<BootstrapResult>(
        `/admin/companies/${company.id}/bootstrap`,
        { name: bootstrapResult.name, email: bootstrapResult.email },
      );
      setBootstrapResult(res.data);
    } catch {
      // Leave the failed state standing: it already says what to do, and
      // replacing it with a second error would lose the address to retry.
    } finally {
      setResending(false);
    }
  };

  const handleToggle = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setToggling(true);
    try {
      const action = company.is_active ? 'deactivate' : 'reactivate';
      await axiosClient.patch(`/admin/companies/${company.id}/${action}`);
      onToggle(company.id, !company.is_active);
    } finally {
      setToggling(false);
    }
  };

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={() => navigate(`/superadmin/companies/${company.id}`)}
      className="card hover:shadow-md hover:border-violet-500/30 transition-all cursor-pointer group"
    >
      <div className="flex items-start justify-between gap-4 flex-wrap">
        {/* Left: identity */}
        <div className="flex items-start gap-3">
          <div className={`mt-0.5 flex items-center justify-center w-9 h-9 rounded-xl shrink-0 ${
            company.is_active ? 'bg-success/10' : 'bg-muted/30'
          }`}>
            <Building2 className={`w-4 h-4 ${company.is_active ? 'text-success' : 'text-muted-foreground'}`} />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <p className="font-semibold text-sm group-hover:text-violet-400 transition-colors">{company.name}</p>
              {company.is_active ? (
                <span className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full bg-success/10 text-success font-medium">
                  <ShieldCheck className="w-3 h-3" /> Active
                </span>
              ) : (
                <span className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full bg-muted/40 text-muted-foreground font-medium">
                  <ShieldAlert className="w-3 h-3" /> Inactive
                </span>
              )}
              {!company.has_admin && (
                <span className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full bg-warning/10 text-warning font-medium">
                  <UserX className="w-3 h-3" /> No admin
                </span>
              )}
              {/* Only non-live tenants are marked. Badging every live company
                  would make the common case noisy and the exception invisible
                  — the opposite of what this is for. */}
              {company.data_class !== 'live' && (
                <span className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded-full bg-info/10 text-info font-medium uppercase tracking-wide">
                  {company.data_class}
                </span>
              )}
            </div>
            <div className="flex items-center gap-3 mt-0.5 flex-wrap">
              <span className="text-xs text-muted-foreground font-mono">{company.slug}</span>
              {company.amazon_dsp_code && (
                <span className="text-xs text-muted-foreground">{company.amazon_dsp_code}</span>
              )}
              <span className="text-xs text-muted-foreground">{company.timezone}</span>
              <span className="text-xs text-muted-foreground">
                Created {new Date(company.created_at).toLocaleDateString()}
              </span>
            </div>
          </div>
        </div>

        {/* Right: actions + chevron */}
        <div className="flex items-center gap-2">
          <button
            onClick={handleToggle}
            disabled={toggling}
            className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1.5 rounded-lg transition-colors ${
              company.is_active
                ? 'text-danger hover:bg-danger/10'
                : 'text-success hover:bg-success/10'
            }`}
          >
            {company.is_active
              ? <><XCircle className="w-3.5 h-3.5" /> Deactivate</>
              : <><CheckCircle2 className="w-3.5 h-3.5" /> Reactivate</>
            }
          </button>
          <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-violet-400 transition-colors" />
        </div>
      </div>

      {/* Bootstrap section */}
      {company.is_active && (
        <div className="mt-3 pt-3 border-t border-border/40">
          {bootstrapResult ? (
            <div
              className={`flex items-center gap-2 text-xs ${bootstrapResult.invite_sent ? 'text-success' : 'text-warning'}`}
              onClick={e => e.stopPropagation()}
            >
              {bootstrapResult.invite_sent ? (
                <><CheckCircle2 className="w-3.5 h-3.5" /> Invite sent to {bootstrapResult.email}</>
              ) : (
                <>
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  <span>Admin created, but the invite to {bootstrapResult.email} could not be sent.</span>
                  <button
                    type="button"
                    onClick={resendInvite}
                    disabled={resending}
                    className="shrink-0 underline underline-offset-2 hover:text-foreground disabled:opacity-50"
                  >
                    {resending ? 'Resending…' : 'Resend'}
                  </button>
                </>
              )}
            </div>
          ) : company.owner ? (
            /* ADR-451 D6. The Owner as the SERVER knows them. This is the whole
               fix: the form used to render unconditionally, so an operator
               re-running bootstrap with a corrected address could not see that
               an Owner already existed. */
            <div
              className="flex items-center justify-between gap-3 flex-wrap text-xs"
              onClick={e => e.stopPropagation()}
            >
              <div className="min-w-0">
                <span className="text-muted-foreground">Owner </span>
                <span className="text-foreground font-medium">{company.owner.name}</span>
                {company.owner.email && (
                  <span className="text-muted-foreground font-mono"> · {company.owner.email}</span>
                )}
                {company.owner.pending_email && (
                  <span className="text-warning">
                    {' '}· changing to {company.owner.pending_email}, awaiting confirmation
                  </span>
                )}
              </div>
              <span
                className={
                  company.owner.account_status === 'pending_verification'
                    ? 'text-warning shrink-0'
                    : 'text-success shrink-0'
                }
              >
                {company.owner.account_status === 'pending_verification'
                  ? 'Invite pending'
                  : 'Registered'}
              </span>
            </div>
          ) : (
            <BootstrapForm companyId={company.id} onDone={setBootstrapResult} />
          )}
        </div>
      )}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Companies() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await axiosClient.get<Company[]>('/admin/companies/');
      setCompanies(res.data);
    } catch {
      setError('Failed to load companies.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleCreated = (c: Company) => {
    setCompanies(prev => [c, ...prev]);
    setCreating(false);
  };

  const handleToggle = (id: string, active: boolean) =>
    setCompanies(prev => prev.map(c => c.id === id ? { ...c, is_active: active } : c));

  const active   = companies.filter(c => c.is_active).length;
  const inactive = companies.length - active;

  return (
    <div className="space-y-6 animate-slide-up">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <SectionHeader
          title="Companies"
          description="All DSP tenants onboarded to AsheFlow"
        />
        <div className="flex items-center gap-2">
          <button onClick={load} className="btn-ghost flex items-center gap-1.5 text-sm">
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
          <button
            onClick={() => setCreating(v => !v)}
            className="btn-primary flex items-center gap-2 text-sm"
          >
            <Plus className="w-4 h-4" />
            New Company
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <StatCard label="Total" value={companies.length} icon={Building2} tone="primary" />
        <StatCard label="Active" value={active} icon={CheckCircle2} tone="success" />
        <StatCard label="Inactive" value={inactive} icon={XCircle} tone="danger" />
      </div>

      {/* Inline create form */}
      <AnimatePresence>
        {creating && (
          <CreateCompanyForm onCreated={handleCreated} onClose={() => setCreating(false)} />
        )}
      </AnimatePresence>

      {error && <ErrorBanner message={error} />}

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map(i => <SkeletonCard key={i} />)}
        </div>
      ) : companies.length === 0 ? (
        <div className="card text-center py-12 text-muted-foreground text-sm">
          No companies yet. Create one above.
        </div>
      ) : (
        <div className="space-y-3">
          {companies.map(c => (
            <CompanyRow key={c.id} company={c} onToggle={handleToggle} />
          ))}
        </div>
      )}
    </div>
  );
}
