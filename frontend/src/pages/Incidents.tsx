import React, { useState, useEffect, useRef } from 'react';
import { AlertTriangle, AlertCircle, Info, CheckCircle, Camera, X, ChevronDown, ChevronUp } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import axiosClient from '../api/axiosClient';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CATEGORIES = [
  { value: 'vehicle',            label: 'Vehicle Issue' },
  { value: 'injury',             label: 'Injury' },
  { value: 'stolen_packages',    label: 'Stolen Packages' },
  { value: 'customer_complaint', label: 'Customer Complaint' },
  { value: 'route_issue',        label: 'Route Issue' },
  { value: 'crew_conduct',       label: 'Crew Conduct' },
  { value: 'safety_hazard',      label: 'Safety Hazard' },
  { value: 'other',              label: 'Other' },
];

const CATEGORY_DEFAULT_SEVERITY: Record<string, string> = {
  injury:             'critical',
  stolen_packages:    'warning',
  vehicle:            'warning',
  crew_conduct:       'warning',
  safety_hazard:      'warning',
  customer_complaint: 'info',
  route_issue:        'info',
  other:              'info',
};

const SEVERITY_RANK: Record<string, number> = { info: 0, warning: 1, critical: 2 };

const todayStr = () => new Date().toISOString().split('T')[0];

const fileToDataUrl = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result as string);
    r.onerror = reject;
    r.readAsDataURL(file);
  });

// ---------------------------------------------------------------------------
// Severity UI helpers
// ---------------------------------------------------------------------------

function SeverityBadge({ severity }: { severity: string }) {
  if (severity === 'critical') return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-danger/15 text-danger">
      <AlertCircle className="w-3 h-3" /> Critical
    </span>
  );
  if (severity === 'warning') return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-warning/15 text-warning">
      <AlertTriangle className="w-3 h-3" /> Warning
    </span>
  );
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-bold bg-info/15 text-info">
      <Info className="w-3 h-3" /> Info
    </span>
  );
}

function CategoryLabel({ category }: { category: string }) {
  const found = CATEGORIES.find(c => c.value === category);
  return <span>{found ? found.label : category}</span>;
}

// ---------------------------------------------------------------------------
// Submit Form
// ---------------------------------------------------------------------------

function IncidentForm({ employeeId, reporterName, onSubmitted }: {
  employeeId: string;
  reporterName: string;
  onSubmitted: () => void;
}) {
  const [category, setCategory] = useState('');
  const [severity, setSeverity] = useState('info');
  const [description, setDescription] = useState('');
  const [photoUrl, setPhotoUrl] = useState<string | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);

  // Stolen packages
  const [incidentTime, setIncidentTime] = useState('');
  const [packagesTba, setPackagesTba] = useState('');
  const [incidentLocation, setIncidentLocation] = useState('');
  const [witnessName, setWitnessName] = useState('');

  // Injury
  const [bodyPart, setBodyPart] = useState('');
  const [medicalAttention, setMedicalAttention] = useState<boolean | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-set severity when category changes
  useEffect(() => {
    if (!category) return;
    const def = CATEGORY_DEFAULT_SEVERITY[category] ?? 'info';
    setSeverity(def);
  }, [category]);

  const handlePhoto = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPhotoPreview(URL.createObjectURL(file));
    setPhotoUrl(await fileToDataUrl(file));
  };

  const handleSubmit = async () => {
    if (!category) return setError('Please select a category.');
    if (!description.trim()) return setError('Please enter a description.');
    setError('');
    setLoading(true);
    try {
      await axiosClient.post('/incidents/', {
        reporter_id: employeeId,
        date: todayStr(),
        category,
        severity,
        description,
        photo_url: photoUrl || undefined,
        incident_time: incidentTime || undefined,
        packages_tba: packagesTba ? parseInt(packagesTba) : undefined,
        incident_location: incidentLocation || undefined,
        witness_name: witnessName || undefined,
        body_part_affected: bodyPart || undefined,
        medical_attention_required: medicalAttention ?? undefined,
      });
      // Reset
      setCategory(''); setSeverity('info'); setDescription('');
      setPhotoUrl(null); setPhotoPreview(null);
      setIncidentTime(''); setPackagesTba(''); setIncidentLocation(''); setWitnessName('');
      setBodyPart(''); setMedicalAttention(null);
      onSubmitted();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to submit incident.');
    } finally {
      setLoading(false);
    }
  };

  const minSeverity = category ? CATEGORY_DEFAULT_SEVERITY[category] ?? 'info' : 'info';
  const availableSeverities = ['info', 'warning', 'critical'].filter(
    s => SEVERITY_RANK[s] >= SEVERITY_RANK[minSeverity]
  );

  return (
    <div className="card space-y-5">
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-danger/10">
          <AlertTriangle className="w-4 h-4 text-danger" />
        </div>
        <h2 className="section-title">Report an Incident</h2>
      </div>

      {/* Reporter — read only */}
      <div>
        <label className="block text-xs font-semibold text-subtle uppercase tracking-wider mb-1">Reporter</label>
        <p className="text-sm font-medium text-foreground">{reporterName}</p>
      </div>

      {/* Category */}
      <div>
        <label className="block text-xs font-semibold text-subtle uppercase tracking-wider mb-1">Category *</label>
        <select
          value={category}
          onChange={e => setCategory(e.target.value)}
          className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
        >
          <option value="">Select a category…</option>
          {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
        </select>
      </div>

      {/* Severity */}
      {category && (
        <div>
          <label className="block text-xs font-semibold text-subtle uppercase tracking-wider mb-2">Severity</label>
          <div className="flex gap-2">
            {availableSeverities.map(s => (
              <button
                key={s}
                onClick={() => setSeverity(s)}
                className={`flex-1 py-2 rounded-xl text-xs font-bold border transition-colors capitalize
                  ${severity === s
                    ? s === 'critical' ? 'bg-danger text-white border-danger'
                    : s === 'warning'  ? 'bg-warning text-white border-warning'
                    : 'bg-info text-white border-info'
                    : 'bg-background text-muted-foreground border-border hover:border-primary/40'
                  }`}
              >
                {s}
              </button>
            ))}
          </div>
          {minSeverity !== 'info' && (
            <p className="text-xs text-subtle mt-1">Minimum severity for this category: <span className="font-medium capitalize">{minSeverity}</span></p>
          )}
        </div>
      )}

      {/* Stolen packages fields */}
      {category === 'stolen_packages' && (
        <div className="space-y-3 p-4 rounded-xl bg-warning/5 border border-warning/20">
          <p className="text-xs font-bold text-warning uppercase tracking-wider">Stolen Packages Details</p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-subtle mb-1">Time of Incident</label>
              <input type="time" value={incidentTime} onChange={e => setIncidentTime(e.target.value)}
                className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
            </div>
            <div>
              <label className="block text-xs text-subtle mb-1">Packages TBA</label>
              <input type="number" min="1" value={packagesTba} onChange={e => setPackagesTba(e.target.value)}
                placeholder="Number of packages"
                className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
            </div>
          </div>
          <div>
            <label className="block text-xs text-subtle mb-1">Location / Address *</label>
            <input type="text" value={incidentLocation} onChange={e => setIncidentLocation(e.target.value)}
              placeholder="Street address or landmark"
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
          </div>
          <div>
            <label className="block text-xs text-subtle mb-1">Witness Name (optional)</label>
            <input type="text" value={witnessName} onChange={e => setWitnessName(e.target.value)}
              placeholder="Full name of any witness"
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
          </div>
        </div>
      )}

      {/* Injury fields */}
      {category === 'injury' && (
        <div className="space-y-3 p-4 rounded-xl bg-danger/5 border border-danger/20">
          <p className="text-xs font-bold text-danger uppercase tracking-wider">Injury Details</p>
          <div>
            <label className="block text-xs text-subtle mb-1">Body Part Affected</label>
            <input type="text" value={bodyPart} onChange={e => setBodyPart(e.target.value)}
              placeholder="e.g. left ankle, lower back"
              className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50" />
          </div>
          <div>
            <label className="block text-xs text-subtle mb-2">Medical Attention Required?</label>
            <div className="flex gap-3">
              {[true, false].map(val => (
                <button key={String(val)} onClick={() => setMedicalAttention(val)}
                  className={`flex-1 py-2 rounded-xl text-xs font-bold border transition-colors
                    ${medicalAttention === val
                      ? val ? 'bg-danger text-white border-danger' : 'bg-success text-white border-success'
                      : 'bg-background text-muted-foreground border-border hover:border-primary/40'}`}>
                  {val ? 'Yes' : 'No'}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Description */}
      <div>
        <label className="block text-xs font-semibold text-subtle uppercase tracking-wider mb-1">
          Description / Comments *
        </label>
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Describe what happened in as much detail as possible…"
          rows={4}
          className="w-full p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
        />
      </div>

      {/* Photo */}
      <div>
        <label className="block text-xs font-semibold text-subtle uppercase tracking-wider mb-2">Photo (optional)</label>
        <label className="flex items-center justify-center gap-2 w-full py-3 border-2 border-dashed border-border rounded-xl cursor-pointer hover:border-primary/50 transition-colors text-sm text-muted-foreground">
          <Camera className="w-4 h-4" />
          {photoPreview ? 'Retake / Replace Photo' : 'Attach Photo'}
          <input ref={inputRef} type="file" accept="image/*" capture="environment" onChange={handlePhoto} className="hidden" />
        </label>
        {photoPreview && (
          <div className="relative mt-2 inline-block">
            <img src={photoPreview} alt="Preview" className="rounded-xl max-h-40 object-cover border border-border" />
            <button onClick={() => { setPhotoPreview(null); setPhotoUrl(null); }}
              className="absolute top-1 right-1 bg-background/80 rounded-full p-0.5 hover:bg-danger/20">
              <X className="w-3 h-3 text-danger" />
            </button>
          </div>
        )}
      </div>

      {error && <p className="text-xs text-danger">{error}</p>}

      <button onClick={handleSubmit} disabled={loading || !category}
        className="btn-primary w-full disabled:opacity-50">
        {loading ? 'Submitting…' : 'Submit Incident Report'}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// My Incidents History
// ---------------------------------------------------------------------------

function MyIncidents({ employeeId, refreshKey }: { employeeId: string; refreshKey: number }) {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    if (!employeeId) return;
    axiosClient.get('/incidents/my', { params: { reporter_id: employeeId } })
      .then(res => setIncidents(res.data))
      .catch(console.error);
  }, [employeeId, refreshKey]);

  if (incidents.length === 0) return (
    <div className="card text-center py-8 text-subtle text-sm">No incidents submitted yet.</div>
  );

  return (
    <div className="card space-y-3">
      <h2 className="section-title">My Submitted Incidents</h2>
      {incidents.map(inc => (
        <div key={inc.id} className="rounded-xl border border-border bg-background overflow-hidden">
          <button
            onClick={() => setExpanded(expanded === inc.id ? null : inc.id)}
            className="w-full flex items-center justify-between p-3 text-left hover:bg-accent/30 transition-colors"
          >
            <div className="flex items-center gap-3 min-w-0">
              <SeverityBadge severity={inc.severity} />
              <span className="text-sm font-medium text-foreground truncate"><CategoryLabel category={inc.category} /></span>
              <span className="text-xs text-subtle shrink-0">{inc.date}</span>
            </div>
            <div className="flex items-center gap-2 shrink-0 ml-2">
              {inc.resolved
                ? <span className="text-xs text-success font-medium flex items-center gap-1"><CheckCircle className="w-3 h-3" />Resolved</span>
                : <span className="text-xs text-subtle">Open</span>}
              {expanded === inc.id ? <ChevronUp className="w-4 h-4 text-subtle" /> : <ChevronDown className="w-4 h-4 text-subtle" />}
            </div>
          </button>
          {expanded === inc.id && (
            <div className="px-4 pb-4 space-y-2 border-t border-border/50 pt-3">
              <p className="text-sm text-foreground">{inc.description}</p>
              {inc.incident_location && <p className="text-xs text-subtle">Location: {inc.incident_location}</p>}
              {inc.packages_tba && <p className="text-xs text-subtle">Packages TBA: {inc.packages_tba}</p>}
              {inc.incident_time && <p className="text-xs text-subtle">Time of incident: {inc.incident_time}</p>}
              {inc.witness_name && <p className="text-xs text-subtle">Witness: {inc.witness_name}</p>}
              {inc.body_part_affected && <p className="text-xs text-subtle">Body part: {inc.body_part_affected}</p>}
              {inc.medical_attention_required != null && (
                <p className="text-xs text-subtle">Medical attention: {inc.medical_attention_required ? 'Yes' : 'No'}</p>
              )}
              {inc.driver_id && inc.driver_name && (
                <p className="text-xs text-subtle">Driver: <span className="font-medium text-foreground">{inc.driver_name}</span></p>
              )}
              {inc.photo_url && (
                <img src={inc.photo_url} alt="Incident" className="rounded-xl max-h-40 object-cover border border-border mt-2" />
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Management View — full table with filters
// ---------------------------------------------------------------------------

function ManagementView() {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [filterSeverity, setFilterSeverity] = useState('');
  const [filterCategory, setFilterCategory] = useState('');
  const [filterResolved, setFilterResolved] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [resolving, setResolving] = useState<string | null>(null);

  const load = () => {
    const params: any = {};
    if (filterSeverity) params.severity = filterSeverity;
    if (filterCategory) params.category = filterCategory;
    if (filterResolved !== '') params.resolved = filterResolved === 'true';
    axiosClient.get('/incidents/', { params })
      .then(res => setIncidents(res.data))
      .catch(console.error);
  };

  useEffect(() => { load(); }, [filterSeverity, filterCategory, filterResolved]);

  const handleResolve = async (id: string) => {
    setResolving(id);
    try {
      await axiosClient.patch(`/incidents/${id}/resolve`);
      load();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to resolve.');
    } finally {
      setResolving(null);
    }
  };

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="card">
        <div className="flex flex-wrap gap-3">
          <select value={filterSeverity} onChange={e => setFilterSeverity(e.target.value)}
            className="p-2 rounded-xl border border-border bg-background text-sm focus:outline-none flex-1 min-w-[120px]">
            <option value="">All severities</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
          <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)}
            className="p-2 rounded-xl border border-border bg-background text-sm focus:outline-none flex-1 min-w-[160px]">
            <option value="">All categories</option>
            {CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
          </select>
          <select value={filterResolved} onChange={e => setFilterResolved(e.target.value)}
            className="p-2 rounded-xl border border-border bg-background text-sm focus:outline-none flex-1 min-w-[120px]">
            <option value="">All statuses</option>
            <option value="false">Open</option>
            <option value="true">Resolved</option>
          </select>
        </div>
      </div>

      {incidents.length === 0 ? (
        <div className="card text-center py-10 text-subtle text-sm">No incidents match the selected filters.</div>
      ) : (
        <div className="space-y-2">
          {incidents.map(inc => (
            <div key={inc.id} className={`rounded-xl border overflow-hidden ${
              inc.severity === 'critical' ? 'border-danger/40' :
              inc.severity === 'warning'  ? 'border-warning/40' : 'border-border'
            } bg-background`}>
              <button
                onClick={() => setExpanded(expanded === inc.id ? null : inc.id)}
                className="w-full flex items-center gap-3 p-3 text-left hover:bg-accent/20 transition-colors"
              >
                <SeverityBadge severity={inc.severity} />
                <span className="text-sm font-semibold text-foreground"><CategoryLabel category={inc.category} /></span>
                <span className="text-xs text-subtle">{inc.reporter_name || 'Unknown'}</span>
                {inc.truck_name && <span className="text-xs text-subtle">· {inc.truck_name}</span>}
                <span className="text-xs text-subtle ml-auto shrink-0">{inc.date}</span>
                {inc.resolved
                  ? <span className="text-xs text-success font-medium flex items-center gap-1 shrink-0"><CheckCircle className="w-3 h-3" />Resolved</span>
                  : <span className="text-xs text-warning font-medium shrink-0">Open</span>}
                {expanded === inc.id ? <ChevronUp className="w-4 h-4 text-subtle shrink-0" /> : <ChevronDown className="w-4 h-4 text-subtle shrink-0" />}
              </button>

              {expanded === inc.id && (
                <div className="px-4 pb-4 border-t border-border/50 pt-3 space-y-3">
                  <p className="text-sm text-foreground">{inc.description}</p>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-subtle">
                    {inc.incident_location && <p>Location: <span className="text-foreground">{inc.incident_location}</span></p>}
                    {inc.packages_tba != null && <p>Packages TBA: <span className="text-foreground">{inc.packages_tba}</span></p>}
                    {inc.incident_time && <p>Time: <span className="text-foreground">{inc.incident_time}</span></p>}
                    {inc.witness_name && <p>Witness: <span className="text-foreground">{inc.witness_name}</span></p>}
                    {inc.body_part_affected && <p>Body part: <span className="text-foreground">{inc.body_part_affected}</span></p>}
                    {inc.medical_attention_required != null && (
                      <p>Medical attention: <span className="text-foreground">{inc.medical_attention_required ? 'Yes' : 'No'}</span></p>
                    )}
                    {inc.driver_name && <p>Driver: <span className="text-foreground">{inc.driver_name}</span></p>}
                  </div>
                  {inc.photo_url && (
                    <img src={inc.photo_url} alt="Incident" className="rounded-xl max-h-48 object-cover border border-border" />
                  )}
                  {!inc.resolved && (
                    <button
                      onClick={() => handleResolve(inc.id)}
                      disabled={resolving === inc.id}
                      className="btn-primary text-xs disabled:opacity-50"
                    >
                      {resolving === inc.id ? 'Resolving…' : 'Mark Resolved'}
                    </button>
                  )}
                  {inc.resolved && inc.resolved_at && (
                    <p className="text-xs text-subtle">Resolved at {new Date(inc.resolved_at).toLocaleString()}</p>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Incidents() {
  const { groups, user } = useAuth();
  const isManagement = groups.some(r => ['dispatch', 'management', 'admin'].includes(r));
  const isFieldStaff = groups.some(r => ['driver', 'walker', 'trainer', 'trainee'].includes(r));

  const [employeeId, setEmployeeId] = useState('');
  const [reporterName, setReporterName] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeTab, setActiveTab] = useState<'submit' | 'management'>(isFieldStaff ? 'submit' : 'management');

  useEffect(() => {
    if (!user) return;
    axiosClient.get('/employees/').then(res => {
      const self = res.data.find((e: any) => e.discord_id === user.username || e.id === user.userId);
      if (self) { setEmployeeId(self.id); setReporterName(self.name || self.first_name || user.username); }
    }).catch(console.error);
  }, [user]);

  const tabs = [
    ...(isFieldStaff ? [{ key: 'submit', label: 'Submit / My Reports' }] : []),
    ...(isManagement ? [{ key: 'management', label: 'All Incidents' }] : []),
  ] as { key: 'submit' | 'management'; label: string }[];

  return (
    <div className="max-w-4xl mx-auto space-y-6 animate-slide-up">
      <div>
        <h1 className="page-title">Incidents</h1>
        <p className="text-subtle mt-1">Report and track field incidents across your team.</p>
      </div>

      {/* Tabs */}
      {tabs.length > 1 && (
        <div className="flex gap-1 p-1 bg-accent/40 rounded-xl w-fit">
          {tabs.map(tab => (
            <button key={tab.key} onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                activeTab === tab.key ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
              }`}>
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {activeTab === 'submit' && isFieldStaff && employeeId && (
        <div className="space-y-6">
          <IncidentForm
            employeeId={employeeId}
            reporterName={reporterName}
            onSubmitted={() => setRefreshKey(k => k + 1)}
          />
          <MyIncidents employeeId={employeeId} refreshKey={refreshKey} />
        </div>
      )}

      {activeTab === 'management' && isManagement && (
        <ManagementView />
      )}
    </div>
  );
}
