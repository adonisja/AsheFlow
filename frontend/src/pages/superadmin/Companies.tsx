import { errorText } from '../../utils/errorText';
import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  Building2, Plus, RefreshCw, CheckCircle2, XCircle,
  ChevronDown, ChevronUp, Send, AlertTriangle, ChevronRight,
  ShieldCheck, ShieldAlert, X, UserX,
} from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import SectionHeader from '../../components/ui/SectionHeader';
import StatCard from '../../components/ui/StatCard';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { SkeletonCard } from '../../components/ui/Skeleton';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Company {
  id: string;
  name: string;
  slug: string;
  amazon_dsp_code: string | null;
  timezone: string;
  is_active: boolean;
  created_at: string;
  has_admin: boolean;
  /** ADR-280 — is this tenant's data real? Super admin is the one
   *  cross-tenant surface, so it is the one place this has to show. */
  data_class: 'live' | 'seed' | 'demo';
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

  const handleNameChange = (v: string) => {
    setName(v);
    setSlug(v.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const res = await axiosClient.post<Company>('/admin/companies/', {
        name: name.trim(),
        slug: slug.trim(),
        amazon_dsp_code: dspCode.trim() || null,
        timezone,
      });
      onCreated(res.data);
      onClose();
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
        <h3 className="font-semibold text-sm">Create New Company</h3>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>
      {error && <ErrorBanner message={error} className="mb-3" />}
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
            <select
              className="input-field"
              value={timezone}
              onChange={e => setTimezone(e.target.value)}
            >
              <option value="America/New_York">America/New_York (ET)</option>
              <option value="America/Chicago">America/Chicago (CT)</option>
              <option value="America/Denver">America/Denver (MT)</option>
              <option value="America/Los_Angeles">America/Los_Angeles (PT)</option>
              <option value="America/Phoenix">America/Phoenix (AZ)</option>
              <option value="America/Anchorage">America/Anchorage (AKT)</option>
              <option value="Pacific/Honolulu">Pacific/Honolulu (HT)</option>
            </select>
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
              {bootstrapResult.invite_sent
                ? <><CheckCircle2 className="w-3.5 h-3.5" /> Invite sent to {bootstrapResult.email}</>
                : <><AlertTriangle className="w-3.5 h-3.5" /> Admin created but email delivery failed. Retry to resend.</>
              }
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
