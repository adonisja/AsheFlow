import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import axiosClient from '../api/axiosClient';
import { getLocalYMD } from '../utils/date';
import { useAuth } from '../contexts/AuthContext';
import {
  Shield, Users, Truck, AlertTriangle, ClipboardCheck,
  BarChart2, RefreshCw, CheckCircle2, ArrowRight, Zap,
  FlaskConical, ChevronDown, ChevronUp, X,
} from 'lucide-react';
import SectionHeader from '../components/ui/SectionHeader';
import StatCard from '../components/ui/StatCard';
import MotionCard from '../components/ui/MotionCard';
import ErrorBanner from '../components/ui/ErrorBanner';
import { SkeletonCard } from '../components/ui/Skeleton';

type Employee = {
  id: string;
  name: string;
  role: string;
  is_active: boolean;
};

type TruckType = {
  id: string;
  name: string;
  is_active: boolean;
};

type SeedPreviewRow = {
  tracking_id: string;
  address: string;
  bag_id: string;
  package_type: string;
  latitude: number;
  longitude: number;
};

type SeedManifestData = {
  sort_date: string;
  package_count: number;
  tote_count: number;
  ov_count: number;
  truck_count: number;
  truck_names: string[];
  preview_rows: SeedPreviewRow[];
  csv_b64: string;
};

type SeedPhase = 'idle' | 'loading' | 'ready' | 'uploading' | 'done' | 'error';

export default function AdminDashboard() {
  const navigate = useNavigate();
  const { groups } = useAuth();
  const isAdmin = groups.includes('admin');

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [trucks, setTrucks] = useState<TruckType[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [trainingToday, setTrainingToday] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = () => {
    setLoading(true);
    setError(null);
    const today = getLocalYMD();
    Promise.allSettled([
      axiosClient.get('/employees/?include_inactive=true&limit=500').then(r => setEmployees(r.data)),
      axiosClient.get('/trucks/?include_inactive=true').then(r => setTrucks(r.data)),
      axiosClient.get('/incidents/?resolved=false').then(r => setIncidents(r.data)),
      axiosClient.get('/training/daily/active').then(r => setTrainingToday(r.data)),
      axiosClient.get(`/dispatch/${today}/confirmations`).then(r => {
        const count = Object.values(r.data.confirmations ?? {}).filter(s => s === 'pending').length;
        setPendingConfirmCount(count);
        setConfirmDate(today);
      }).catch(() => {}),
    ]).then(results => {
      if (results.some(r => r.status === 'rejected')) {
        setError('Some dashboard data failed to load. Refresh to retry.');
      }
    }).finally(() => setLoading(false));
  };

  useEffect(() => { fetchAll(); }, []);

  const roleGroups = employees.reduce<Record<string, number>>((acc, e) => {
    acc[e.role] = (acc[e.role] || 0) + 1;
    return acc;
  }, {});

  const ROLE_ORDER = ['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin'];
  const roleRows = ROLE_ORDER
    .filter(r => roleGroups[r])
    .map(r => ({ role: r, count: roleGroups[r] }));

  // ---------------------------------------------------------------------------
  // Confirm-all tool (temporary dev aid)
  // ---------------------------------------------------------------------------
  const [confirmAllState, setConfirmAllState] = useState<
    'idle' | 'loading' | 'done' | 'error'
  >('idle');
  const [confirmAllCount, setConfirmAllCount] = useState<number | null>(null);
  const [pendingConfirmCount, setPendingConfirmCount] = useState(0);
  const [confirmDate, setConfirmDate] = useState<string>(getLocalYMD());

  const handleConfirmAll = async () => {
    setConfirmAllState('loading');
    try {
      const res = await axiosClient.post<{ date: string; confirmed_count: number }>(
        `/dispatch/${confirmDate}/confirmations/confirm-all`
      );
      setConfirmAllCount(res.data.confirmed_count);
      setConfirmAllState('done');
      setPendingConfirmCount(0);
    } catch {
      setConfirmAllState('error');
    }
  };

  // ---------------------------------------------------------------------------
  // Test Manifest Generator (admin-only dev tool)
  // ---------------------------------------------------------------------------
  const [seedDate, setSeedDate] = useState<string>(getLocalYMD());
  const [seedPhase, setSeedPhase] = useState<SeedPhase>('idle');
  const [seedData, setSeedData] = useState<SeedManifestData | null>(null);
  const [seedError, setSeedError] = useState<string | null>(null);
  const [seedPreviewExpanded, setSeedPreviewExpanded] = useState(false);
  const [uploadResult, setUploadResult] = useState<{ package_count: number } | null>(null);

  const handleGenerateManifest = async () => {
    setSeedPhase('loading');
    setSeedError(null);
    setSeedData(null);
    try {
      const res = await axiosClient.post<SeedManifestData>(`/sort/seed-manifest?sort_date=${seedDate}`);
      setSeedData(res.data);
      setSeedPhase('ready');
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? 'Failed to generate manifest.';
      setSeedError(typeof detail === 'string' ? detail : JSON.stringify(detail));
      setSeedPhase('error');
    }
  };

  const handleConfirmUpload = async () => {
    if (!seedData) return;
    setSeedPhase('uploading');
    try {
      const csvBytes = Uint8Array.from(atob(seedData.csv_b64), c => c.charCodeAt(0));
      const blob = new Blob([csvBytes], { type: 'text/csv' });
      const form = new FormData();
      form.append('file', blob, 'manifest_seed.csv');
      form.append('sort_date', seedData.sort_date);
      const res = await axiosClient.post<{ package_count: number }>('/sort/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setUploadResult(res.data);
      setSeedPhase('done');
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? 'Upload failed.';
      setSeedError(typeof detail === 'string' ? detail : JSON.stringify(detail));
      setSeedPhase('error');
    }
  };

  const handleDiscardManifest = () => {
    setSeedData(null);
    setSeedError(null);
    setSeedPhase('idle');
    setUploadResult(null);
    setSeedPreviewExpanded(false);
  };

  const handleResolveIncident = (id: string) => {
    axiosClient.patch(`/incidents/${id}/resolve`).then(() => {
      setIncidents(prev => prev.filter(i => i.id !== id));
    }).catch(() => setError('Failed to resolve incident.'));
  };

  if (loading) {
    return (
      <div className="space-y-8">
        <SectionHeader eyebrow="System" title="Admin Dashboard" />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {Array.from({ length: 3 }).map((_, i) => <SkeletonCard key={i} className="h-48" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <SectionHeader
        eyebrow="System"
        title={<span className="flex items-center gap-2"><Shield className="w-7 h-7 text-primary" />Admin Dashboard</span>}
        description="System overview — employees, trucks, incidents, and training."
        actions={
          <button onClick={fetchAll} className="btn-ghost flex items-center gap-2 text-sm">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        }
      />

      <ErrorBanner message={error} />

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          label="Active Employees"
          value={employees.filter(e => e.is_active).length}
          icon={Users}
          tone="info"
          delay={0}
        />
        <StatCard
          label="Active Trucks"
          value={trucks.filter(t => t.is_active).length}
          icon={Truck}
          tone="primary"
          delay={0.07}
        />
        <StatCard
          label="Open Incidents"
          value={incidents.length}
          icon={AlertTriangle}
          tone={incidents.length > 0 ? 'danger' : 'success'}
          delay={0.14}
          hint={incidents.length === 0 ? 'All clear' : undefined}
        />
        <StatCard
          label="Training Today"
          value={trainingToday.length}
          icon={ClipboardCheck}
          tone="teal"
          delay={0.21}
        />
      </div>

      {/* Operations Tool — only shown when pending confirmations exist */}
      {(pendingConfirmCount > 0 || confirmAllState === 'loading' || confirmAllState === 'done' || confirmAllState === 'error') && (
      <div className="flex items-center gap-4 px-4 py-3 rounded-2xl border border-warning/40 bg-warning/5">
        <Zap className="w-5 h-5 text-warning shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">Operations Tool — Confirm All Pending</p>
          <p className="text-xs text-muted-foreground">
            Marks every pending dispatch confirmation for <span className="font-medium text-foreground">{confirmDate}</span> as confirmed on behalf of each employee.
          </p>
          {confirmAllState === 'done' && (
            <p className="text-xs text-success font-medium mt-0.5">
              {confirmAllCount === 0
                ? 'No pending confirmations found.'
                : `Confirmed ${confirmAllCount} employee${confirmAllCount === 1 ? '' : 's'}.`}
            </p>
          )}
          {confirmAllState === 'error' && (
            <p className="text-xs text-danger font-medium mt-0.5">Failed — check console or retry.</p>
          )}
        </div>
        <button
          onClick={handleConfirmAll}
          disabled={confirmAllState === 'loading'}
          className="btn-ghost border border-warning/50 text-warning hover:bg-warning/10 flex items-center gap-2 shrink-0 disabled:opacity-50 text-sm"
        >
          {confirmAllState === 'loading' ? (
            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
          ) : (
            <CheckCircle2 className="w-4 h-4" />
          )}
          {confirmAllState === 'loading' ? 'Working…' : 'Confirm All'}
        </button>
      </div>
      )}

      {/* Operations Tool — Test Manifest Generator (admin-only) */}
      {isAdmin && (
        <div className="rounded-2xl border border-warning/40 bg-warning/5 overflow-hidden">
          {/* Header row */}
          <div className="flex items-center gap-3 px-4 py-3">
            <FlaskConical className="w-5 h-5 text-warning shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-foreground">Operations Tool — Test Manifest Generator</p>
              <p className="text-xs text-muted-foreground">
                Generate a synthetic 1,500-package manifest and push it through the full sort pipeline.
                Requires truck dispatch to have run for the selected date.
              </p>
            </div>
          </div>

          {/* Body */}
          <div className="border-t border-warning/20 px-4 py-3 space-y-3">

            {/* Phase: idle or error — show date picker + generate button */}
            {(seedPhase === 'idle' || seedPhase === 'error') && (
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className="block text-xs text-muted-foreground mb-1">Sort date</label>
                  <input
                    type="date"
                    value={seedDate}
                    onChange={e => setSeedDate(e.target.value)}
                    className="input-field text-sm h-9 w-40"
                  />
                </div>
                <button
                  onClick={handleGenerateManifest}
                  className="btn-ghost border border-warning/50 text-warning hover:bg-warning/10 flex items-center gap-2 text-sm h-9 px-3"
                >
                  <FlaskConical className="w-4 h-4" />
                  Generate Manifest
                </button>
                {seedPhase === 'error' && seedError && (
                  <p className="text-xs text-danger font-medium">{seedError}</p>
                )}
              </div>
            )}

            {/* Phase: loading */}
            {seedPhase === 'loading' && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="w-4 h-4 border-2 border-warning border-t-transparent rounded-full animate-spin" />
                Generating 1,500 packages…
              </div>
            )}

            {/* Phase: ready — show summary + preview */}
            {seedPhase === 'ready' && seedData && (
              <div className="space-y-3">
                {/* Summary stats */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label: 'Packages', value: seedData.package_count.toLocaleString() },
                    { label: 'Totes',    value: seedData.tote_count.toLocaleString() },
                    { label: 'OVs',      value: seedData.ov_count.toLocaleString() },
                    { label: 'Trucks',   value: `${seedData.truck_count} (${seedData.truck_names.join(', ')})` },
                  ].map(({ label, value }) => (
                    <div key={label} className="p-2 rounded-xl border border-warning/20 bg-surface-muted/50">
                      <p className="text-xs text-muted-foreground">{label}</p>
                      <p className="text-sm font-semibold text-foreground truncate" title={value}>{value}</p>
                    </div>
                  ))}
                </div>

                {/* Preview toggle */}
                <button
                  onClick={() => setSeedPreviewExpanded(v => !v)}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  {seedPreviewExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                  {seedPreviewExpanded ? 'Hide' : 'Show'} first 20 rows
                </button>

                {seedPreviewExpanded && (
                  <div className="overflow-x-auto rounded-xl border border-border">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-surface-muted/80 text-muted-foreground">
                          <th className="text-left px-3 py-2 font-medium">TBA</th>
                          <th className="text-left px-3 py-2 font-medium">Address</th>
                          <th className="text-left px-3 py-2 font-medium">Bag</th>
                          <th className="text-left px-3 py-2 font-medium">Type</th>
                          <th className="text-left px-3 py-2 font-medium">Lat</th>
                          <th className="text-left px-3 py-2 font-medium">Lng</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border">
                        {seedData.preview_rows.map((row, i) => (
                          <tr key={i} className="hover:bg-surface-muted/40">
                            <td className="px-3 py-1.5 font-mono text-foreground">{row.tracking_id}</td>
                            <td className="px-3 py-1.5 text-foreground max-w-[200px] truncate" title={row.address}>{row.address}</td>
                            <td className="px-3 py-1.5 text-muted-foreground font-mono">{row.bag_id}</td>
                            <td className="px-3 py-1.5">
                              {row.package_type && row.package_type !== '—' ? (
                                <span className="badge badge-warning text-xs">{row.package_type}</span>
                              ) : (
                                <span className="text-muted-foreground">std</span>
                              )}
                            </td>
                            <td className="px-3 py-1.5 font-mono text-muted-foreground">{row.latitude}</td>
                            <td className="px-3 py-1.5 font-mono text-muted-foreground">{row.longitude}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* Action row */}
                <div className="flex items-center gap-3 pt-1">
                  <button
                    onClick={handleConfirmUpload}
                    className="btn-primary flex items-center gap-2 text-sm"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    Looks good — upload for enrichment
                  </button>
                  <button
                    onClick={handleDiscardManifest}
                    className="btn-ghost flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
                  >
                    <X className="w-4 h-4" />
                    Discard
                  </button>
                </div>
              </div>
            )}

            {/* Phase: uploading */}
            {seedPhase === 'uploading' && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="w-4 h-4 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                Uploading manifest and starting enrichment…
              </div>
            )}

            {/* Phase: done */}
            {seedPhase === 'done' && uploadResult && (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm text-success font-medium">
                  <CheckCircle2 className="w-4 h-4" />
                  {uploadResult.package_count.toLocaleString()} packages accepted — enrichment running in background.
                </div>
                <p className="text-xs text-muted-foreground">
                  Poll <span className="font-mono">GET /sort/manifest/{seedDate}/status</span> or go to the Sort page to monitor enrichment, then run the sort.
                </p>
                <button
                  onClick={handleDiscardManifest}
                  className="btn-ghost text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                >
                  <X className="w-3.5 h-3.5" /> Reset
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Mid row — 3 cards */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Workforce breakdown */}
        <MotionCard delay={0.1}>
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <BarChart2 className="w-5 h-5 text-primary" />
            <h2 className="text-base font-semibold text-foreground">Workforce Breakdown</h2>
          </div>
          <div className="space-y-2">
            {roleRows.map(({ role, count }) => (
              <div key={role} className="flex items-center justify-between">
                <span className="text-sm capitalize text-foreground">{role}</span>
                <div className="flex items-center gap-2">
                  <div className="w-24 h-2 rounded-full bg-accent overflow-hidden">
                    <div
                      className="h-full bg-primary rounded-full transition-all duration-500"
                      style={{ width: `${Math.min((count / employees.length) * 100, 100)}%` }}
                    />
                  </div>
                  <span className="text-sm font-semibold text-foreground w-6 text-right">{count}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-4 border-t border-border">
            <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium mb-2">Inactive Employees</p>
            {employees.filter(e => !e.is_active).length === 0 ? (
              <p className="text-sm text-muted-foreground">None.</p>
            ) : (
              <div className="space-y-1">
                {employees.filter(e => !e.is_active).slice(0, 5).map(e => (
                  <p key={e.id} className="text-sm text-muted-foreground capitalize">{e.name} · {e.role}</p>
                ))}
              </div>
            )}
          </div>
        </MotionCard>

        {/* Open incidents */}
        <MotionCard delay={0.17}>
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <AlertTriangle className="w-5 h-5 text-danger" />
            <h2 className="text-base font-semibold text-foreground">Open Incidents</h2>
            {incidents.length > 0 && (
              <span className="ml-auto badge badge-danger">{incidents.length}</span>
            )}
          </div>
          {incidents.length === 0 ? (
            <div className="text-center py-8 opacity-60">
              <CheckCircle2 className="w-10 h-10 mb-3 text-success mx-auto" />
              <p className="text-sm font-medium">All incidents resolved.</p>
            </div>
          ) : (
            <div className="space-y-3 max-h-[280px] overflow-y-auto pr-1">
              {incidents.slice(0, 5).map(inc => (
                <div key={inc.id} className={`p-3 rounded-xl border bg-surface-muted/50 ${
                  inc.severity === 'critical' ? 'border-danger/40' : inc.severity === 'warning' ? 'border-warning/40' : 'border-border'
                }`}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <span className={`text-xs font-bold uppercase tracking-wider ${
                        inc.severity === 'critical' ? 'text-danger' : inc.severity === 'warning' ? 'text-warning' : 'text-info'
                      }`}>{inc.severity}</span>
                      <p className="text-sm font-medium text-foreground mt-0.5">
                        {inc.category?.replace(/_/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase())}
                      </p>
                      <p className="text-xs text-muted-foreground">{inc.reporter_name} · {inc.date}</p>
                    </div>
                    <button
                      onClick={() => handleResolveIncident(inc.id)}
                      className="shrink-0 p-1.5 rounded-lg bg-success/10 hover:bg-success/20 text-success transition-colors"
                      title="Mark resolved"
                    >
                      <CheckCircle2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          <button
            onClick={() => navigate('/incidents')}
            className="mt-4 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            View all incidents <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </MotionCard>

        {/* Training today */}
        <MotionCard delay={0.24}>
          <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
            <ClipboardCheck className="w-5 h-5 text-teal" />
            <h2 className="text-base font-semibold text-foreground">Training Sessions Today</h2>
          </div>
          {trainingToday.length === 0 ? (
            <div className="text-center py-8 opacity-60">
              <ClipboardCheck className="w-10 h-10 mb-3 text-muted-foreground mx-auto" />
              <p className="text-sm font-medium">No training sessions today.</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
              {trainingToday.map((t: any) => (
                <div key={t.record?.id} className="p-3 rounded-xl border border-border bg-surface-muted/50">
                  <div className="flex items-center justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">
                        {t.trainee?.name ?? 'Unknown trainee'}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Trainer: {t.trainer?.name ?? 'Unassigned'}
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-xs font-semibold text-foreground">
                        {t.progress?.completed}/{t.progress?.total}
                      </p>
                      <p className="text-xs text-muted-foreground">tasks done</p>
                    </div>
                  </div>
                  {t.progress?.total > 0 && (
                    <div className="mt-2 h-1.5 rounded-full bg-accent overflow-hidden">
                      <div
                        className="h-full bg-teal rounded-full transition-all duration-500"
                        style={{ width: `${(t.progress.completed / t.progress.total) * 100}%` }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </MotionCard>
      </div>

    </div>
  );
}
