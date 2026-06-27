/**
 * BulkImportModal — 3-step employee bulk import flow.
 *
 * Step 1: Upload — file picker accepting .csv, .xlsx, .xls, .json
 * Step 2: Preview — editable table with inline validation before submitting
 * Step 3: Results — per-row created / skipped / failed summary with CSV export
 *
 * Accessible to management and admin only (enforced at the call site and backend).
 */

import React, { useRef, useState, useCallback } from 'react';
import Papa from 'papaparse';
import * as XLSX from 'xlsx';
import {
  X, Upload, CheckCircle2, XCircle, AlertTriangle,
  ChevronDown, Download, ArrowRight, RotateCcw,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { getLocalYMD } from '../utils/date';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

const ROLES = ['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin'] as const;
type RoleStr = typeof ROLES[number];

type ImportRow = {
  name: string;
  email: string;
  discord_id: string;
  role: RoleStr;
  phone_number: string;
  hr_system_id_adp: string;  // ADP associateOID — read-only in preview, empty string for non-ADP imports
  // client-only validation state
  _errors: Partial<Record<'name' | 'email' | 'discord_id' | 'role', string>>;
};

type ImportResult = {
  row: number;
  status: 'created' | 'skipped' | 'failed';
  name: string;
  email: string;
  reason?: string;
};

type Step = 'upload' | 'preview' | 'results';

// ---------------------------------------------------------------------------
// Column alias normalization
// ---------------------------------------------------------------------------

const ALIASES: Record<string, keyof ImportRow> = {
  // Name
  name:          'name',
  full_name:     'name',
  fullname:      'name',
  employee_name: 'name',
  // Email
  email:               'email',
  email_address:       'email',
  work_email:          'email',
  business_email:      'email',
  home_email:          'email',
  // Discord
  discord:       'discord_id',
  discord_id:    'discord_id',
  discord_user:  'discord_id',
  discordid:     'discord_id',
  // Role
  role:          'role',
  position:      'role',
  job_title:     'role',
  title:         'role',
  // Phone
  phone:           'phone_number',
  phone_number:    'phone_number',
  phonenumber:     'phone_number',
  mobile:          'phone_number',
  business_phone:  'phone_number',
  // ADP associateOID
  'file_#':          'hr_system_id_adp',
  file_number:       'hr_system_id_adp',
  associate_id:      'hr_system_id_adp',
  associateid:       'hr_system_id_adp',
  associateoid:      'hr_system_id_adp',
  hr_system_id_adp:  'hr_system_id_adp',
};

// ADP job title → AsheFlow role translation.
// Unrecognized titles fall back to 'walker' and are flagged in the preview.
const ADP_ROLE_MAP: Record<string, RoleStr> = {
  'delivery associate':         'walker',
  'delivery associate i':       'walker',
  'delivery associate ii':      'walker',
  'da':                         'walker',
  'dispatcher':                 'dispatch',
  'dispatch':                   'dispatch',
  'delivery associate manager': 'management',
  'dsp owner':                  'management',
  'owner':                      'management',
  'manager':                    'management',
  'driver':                     'driver',
  'lead driver':                'driver',
  'trainer':                    'trainer',
  'lead trainer':               'trainer',
  'trainee':                    'trainee',
};

function normalizeKey(raw: string): keyof ImportRow | null {
  return ALIASES[raw.toLowerCase().trim().replace(/\s+/g, '_')] ?? null;
}

function translateRole(raw: string): RoleStr {
  return ADP_ROLE_MAP[raw.toLowerCase().trim()] ?? 'walker';
}

// ---------------------------------------------------------------------------
// Row validation
// ---------------------------------------------------------------------------

function validateRow(row: ImportRow): ImportRow['_errors'] {
  const errors: ImportRow['_errors'] = {};
  if (!row.name.trim())       errors.name       = 'Required';
  if (!row.email.trim())      errors.email      = 'Required';
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(row.email)) errors.email = 'Invalid email';
  if (row.discord_id.trim() && !/^\d{17,20}$/.test(row.discord_id.trim())) errors.discord_id = 'Must be a numeric snowflake ID (17-20 digits)';
  if (!ROLES.includes(row.role as RoleStr)) errors.role = 'Invalid role';
  return errors;
}

// ---------------------------------------------------------------------------
// File parsing
// ---------------------------------------------------------------------------

function parseObjects(objs: Record<string, string>[]): ImportRow[] {
  return objs.map(obj => {
    const normalized: Partial<ImportRow> = {};
    // Track raw first/last name columns for ADP split-name handling
    let firstName = '';
    let lastName  = '';

    for (const [k, v] of Object.entries(obj)) {
      const key = k.toLowerCase().trim().replace(/\s+/g, '_');
      if (key === 'first_name' || key === 'firstname') { firstName = String(v ?? '').trim(); continue; }
      if (key === 'last_name'  || key === 'lastname')  { lastName  = String(v ?? '').trim(); continue; }
      const mapped = normalizeKey(k);
      if (mapped) (normalized as any)[mapped] = String(v ?? '').trim();
    }

    // ADP exports First Name + Last Name separately — combine if name not already set
    if (!normalized.name && (firstName || lastName)) {
      normalized.name = [firstName, lastName].filter(Boolean).join(' ');
    }

    // Translate ADP job title → AsheFlow role if the raw value isn't already a valid role
    let resolvedRole: RoleStr;
    if (normalized.role && ROLES.includes(normalized.role as RoleStr)) {
      resolvedRole = normalized.role as RoleStr;
    } else if (normalized.role) {
      resolvedRole = translateRole(normalized.role);
    } else {
      resolvedRole = 'walker';
    }

    const row: ImportRow = {
      name:             normalized.name             ?? '',
      email:            normalized.email            ?? '',
      discord_id:       normalized.discord_id       ?? '',
      role:             resolvedRole,
      phone_number:     normalized.phone_number     ?? '',
      hr_system_id_adp: normalized.hr_system_id_adp ?? '',
      _errors:          {},
    };
    row._errors = validateRow(row);
    return row;
  });
}

async function parseFile(file: File): Promise<ImportRow[]> {
  const ext = file.name.split('.').pop()?.toLowerCase();

  if (ext === 'json') {
    const text = await file.text();
    const data = JSON.parse(text);
    const arr = Array.isArray(data) ? data : data.employees ?? data.data ?? [];
    return parseObjects(arr);
  }

  if (ext === 'csv') {
    return new Promise((resolve, reject) => {
      Papa.parse<Record<string, string>>(file, {
        header: true,
        skipEmptyLines: true,
        complete: r => resolve(parseObjects(r.data)),
        error: reject,
      });
    });
  }

  if (ext === 'xlsx' || ext === 'xls') {
    const buf = await file.arrayBuffer();
    const wb  = XLSX.read(buf, { type: 'array' });
    const ws  = wb.Sheets[wb.SheetNames[0]];
    const data = XLSX.utils.sheet_to_json<Record<string, string>>(ws, { defval: '' });
    return parseObjects(data);
  }

  throw new Error(`Unsupported file type: .${ext}`);
}

// ---------------------------------------------------------------------------
// Results CSV export
// ---------------------------------------------------------------------------

function exportResults(results: ImportResult[]) {
  const rows = [
    ['Row', 'Status', 'Name', 'Email', 'Reason'],
    ...results.map(r => [r.row, r.status, r.name, r.email, r.reason ?? '']),
  ];
  const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `import-results-${getLocalYMD()}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null;
  return <p className="text-xs text-danger mt-0.5">{msg}</p>;
}

// ---------------------------------------------------------------------------
// Step 1 — Upload
// ---------------------------------------------------------------------------

function UploadStep({ onParsed, onClose }: {
  onParsed: (rows: ImportRow[]) => void;
  onClose: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [parsing,  setParsing]  = useState(false);
  const [error,    setError]    = useState('');

  const handle = useCallback(async (file: File) => {
    if (file.size > 2 * 1024 * 1024) {
      setError('File too large. Maximum file size is 2 MB.');
      return;
    }
    setParsing(true);
    setError('');
    try {
      const rows = await parseFile(file);
      if (rows.length === 0) { setError('No rows found in the file.'); return; }
      if (rows.length > 200) { setError('Maximum 200 rows per import. Split into smaller files.'); return; }
      onParsed(rows);
    } catch (e: any) {
      setError(e?.message ?? 'Failed to parse file.');
    } finally {
      setParsing(false);
    }
  }, [onParsed]);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handle(file);
  };

  return (
    <div className="p-6 space-y-5">
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-10 flex flex-col items-center gap-3 cursor-pointer transition-colors ${
          dragging ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/50 hover:bg-accent/30'
        }`}
      >
        <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center">
          <Upload className="w-6 h-6 text-primary" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-foreground">Drop your file here or click to browse</p>
          <p className="text-xs text-muted-foreground mt-1">Supports CSV, Excel (.xlsx / .xls), JSON · max 200 rows · max 2 MB</p>
        </div>
        {parsing && (
          <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".csv,.xlsx,.xls,.json"
        className="hidden"
        onChange={e => { const f = e.target.files?.[0]; if (f) handle(f); }}
      />

      {error && (
        <div className="text-sm text-danger bg-danger/10 border border-danger/20 rounded-xl px-3 py-2">
          {error}
        </div>
      )}

      <div className="bg-accent/40 rounded-xl p-4 space-y-2">
        <p className="text-xs font-semibold text-foreground uppercase tracking-wider">Expected columns</p>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted-foreground">
          <span><span className="text-foreground font-medium">name</span> — full name (required)</span>
          <span><span className="text-foreground font-medium">email</span> — work email (required)</span>
          <span><span className="text-foreground font-medium">discord_id</span> — Discord snowflake ID (17-20 digit number, optional)</span>
          <span><span className="text-foreground font-medium">role</span> — driver / walker / etc. (required)</span>
          <span><span className="text-foreground font-medium">phone_number</span> — optional</span>
          <span><span className="text-foreground font-medium">Associate ID</span> — ADP associateOID (optional, auto-detected)</span>
        </div>
        <p className="text-xs text-subtle mt-1">ADP exports accepted directly. Split "First Name" / "Last Name" columns are merged automatically. Job titles like "Delivery Associate" are translated to AsheFlow roles.</p>
      </div>

      <div className="flex justify-end">
        <button onClick={onClose} className="btn-ghost">Cancel</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — Preview & Edit
// ---------------------------------------------------------------------------

function PreviewStep({ rows, onChange, onSubmit, onBack, submitting }: {
  rows: ImportRow[];
  onChange: (rows: ImportRow[]) => void;
  onSubmit: () => void;
  onBack: () => void;
  submitting: boolean;
}) {
  const hasErrors = rows.some(r => Object.keys(r._errors).length > 0);
  const errorCount = rows.filter(r => Object.keys(r._errors).length > 0).length;

  const update = (i: number, field: keyof ImportRow, value: string) => {
    const next = rows.map((r, idx) => {
      if (idx !== i) return r;
      const updated = { ...r, [field]: value };
      updated._errors = validateRow(updated);
      return updated;
    });
    onChange(next);
  };

  const removeRow = (i: number) => onChange(rows.filter((_, idx) => idx !== i));

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-3 border-b border-border flex items-center justify-between bg-accent/20">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-foreground">{rows.length} rows</span>
          {hasErrors && (
            <span className="inline-flex items-center gap-1 text-xs text-warning bg-warning/10 border border-warning/20 rounded-full px-2 py-0.5">
              <AlertTriangle className="w-3 h-3" />
              {errorCount} row{errorCount !== 1 ? 's' : ''} with errors
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground">Edit any cell before importing. Rows with errors are highlighted.</p>
      </div>

      <div className="overflow-auto flex-1">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card z-10">
            <tr className="text-left text-muted-foreground uppercase tracking-wider border-b border-border">
              <th className="px-3 py-2 w-8">#</th>
              <th className="px-3 py-2 min-w-[160px]">Name *</th>
              <th className="px-3 py-2 min-w-[190px]">Email *</th>
              <th className="px-3 py-2 min-w-[150px]">Discord Snowflake</th>
              <th className="px-3 py-2 min-w-[130px]">Role *</th>
              <th className="px-3 py-2 min-w-[140px]">Phone</th>
              <th className="px-3 py-2 min-w-[160px]">ADP Associate ID</th>
              <th className="px-3 py-2 w-8"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((row, i) => {
              const hasErr = Object.keys(row._errors).length > 0;
              return (
                <tr key={i} className={hasErr ? 'bg-danger/5' : 'hover:bg-accent/20'}>
                  <td className="px-3 py-1.5 text-muted-foreground">{i + 1}</td>
                  {(['name', 'email', 'discord_id'] as const).map(field => (
                    <td key={field} className="px-3 py-1.5">
                      <input
                        value={row[field]}
                        onChange={e => update(i, field, e.target.value)}
                        className={`w-full bg-transparent border-b outline-none py-0.5 text-xs ${
                          row._errors[field]
                            ? 'border-danger text-danger'
                            : 'border-border focus:border-primary'
                        }`}
                      />
                      <FieldError msg={row._errors[field]} />
                    </td>
                  ))}
                  <td className="px-3 py-1.5">
                    <div className="relative">
                      <select
                        value={row.role}
                        onChange={e => update(i, 'role', e.target.value)}
                        className="w-full bg-transparent border-b border-border outline-none py-0.5 text-xs appearance-none pr-5 capitalize"
                      >
                        {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                      </select>
                      <ChevronDown className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 text-muted-foreground pointer-events-none" />
                    </div>
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      value={row.phone_number}
                      onChange={e => update(i, 'phone_number', e.target.value)}
                      className="w-full bg-transparent border-b border-border outline-none py-0.5 text-xs focus:border-primary"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    {row.hr_system_id_adp
                      ? <span className="text-muted-foreground font-mono">{row.hr_system_id_adp}</span>
                      : <span className="text-subtle italic">—</span>
                    }
                  </td>
                  <td className="px-3 py-1.5">
                    <button
                      onClick={() => removeRow(i)}
                      className="p-0.5 rounded hover:bg-danger/10 text-muted-foreground hover:text-danger transition-colors"
                      title="Remove row"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="px-6 py-4 border-t border-border flex items-center justify-between gap-3">
        <button onClick={onBack} className="btn-ghost text-sm">Back</button>
        <button
          onClick={onSubmit}
          disabled={submitting || rows.length === 0 || hasErrors}
          className="btn-primary flex items-center gap-2 text-sm"
        >
          {submitting
            ? <div className="w-3.5 h-3.5 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
            : <ArrowRight className="w-4 h-4" />}
          {submitting ? `Importing ${rows.length} employees…` : `Import ${rows.length} employee${rows.length !== 1 ? 's' : ''}`}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3 — Results
// ---------------------------------------------------------------------------

function ResultsStep({ results, onClose, onImportMore }: {
  results: ImportResult[];
  onClose: () => void;
  onImportMore: () => void;
}) {
  const created = results.filter(r => r.status === 'created').length;
  const skipped = results.filter(r => r.status === 'skipped').length;
  const failed  = results.filter(r => r.status === 'failed').length;

  return (
    <div className="flex flex-col h-full">
      {/* Summary bar */}
      <div className="px-6 py-4 border-b border-border grid grid-cols-3 gap-4 text-center">
        <div>
          <p className="text-2xl font-bold text-success">{created}</p>
          <p className="text-xs text-muted-foreground mt-0.5">Created</p>
        </div>
        <div>
          <p className="text-2xl font-bold text-warning">{skipped}</p>
          <p className="text-xs text-muted-foreground mt-0.5">Skipped</p>
        </div>
        <div>
          <p className="text-2xl font-bold text-danger">{failed}</p>
          <p className="text-xs text-muted-foreground mt-0.5">Failed</p>
        </div>
      </div>

      {/* Per-row table */}
      <div className="overflow-auto flex-1">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-card z-10">
            <tr className="text-left text-muted-foreground uppercase tracking-wider border-b border-border">
              <th className="px-4 py-2 w-10">#</th>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Email</th>
              <th className="px-4 py-2 w-24">Status</th>
              <th className="px-4 py-2">Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {results.map(r => (
              <tr key={r.row} className={
                r.status === 'created' ? 'bg-success/5' :
                r.status === 'skipped' ? 'bg-warning/5' : 'bg-danger/5'
              }>
                <td className="px-4 py-2 text-muted-foreground">{r.row}</td>
                <td className="px-4 py-2 font-medium text-foreground">{r.name}</td>
                <td className="px-4 py-2 text-muted-foreground truncate max-w-[180px]">{r.email}</td>
                <td className="px-4 py-2">
                  {r.status === 'created' && (
                    <span className="inline-flex items-center gap-1 text-success">
                      <CheckCircle2 className="w-3 h-3" /> Created
                    </span>
                  )}
                  {r.status === 'skipped' && (
                    <span className="inline-flex items-center gap-1 text-warning">
                      <AlertTriangle className="w-3 h-3" /> Skipped
                    </span>
                  )}
                  {r.status === 'failed' && (
                    <span className="inline-flex items-center gap-1 text-danger">
                      <XCircle className="w-3 h-3" /> Failed
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-muted-foreground italic">
                  {r.reason ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="px-6 py-4 border-t border-border flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            onClick={() => exportResults(results)}
            className="btn-ghost text-sm flex items-center gap-2"
          >
            <Download className="w-4 h-4" /> Export results
          </button>
          {(failed > 0 || skipped > 0) && (
            <button
              onClick={onImportMore}
              className="btn-ghost text-sm flex items-center gap-2"
            >
              <RotateCcw className="w-4 h-4" /> Import another file
            </button>
          )}
        </div>
        <button onClick={onClose} className="btn-primary text-sm">Done</button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

type Props = {
  onClose: () => void;
  onComplete: () => void; // called after a successful import so PeopleTab can reload
};

export default function BulkImportModal({ onClose, onComplete }: Props) {
  const [step,       setStep]       = useState<Step>('upload');
  const [rows,       setRows]       = useState<ImportRow[]>([]);
  const [results,    setResults]    = useState<ImportResult[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const handleParsed = (parsed: ImportRow[]) => {
    setRows(parsed);
    setStep('preview');
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const payload = rows.map(r => ({
        name:             r.name,
        email:            r.email,
        discord_id:       r.discord_id.trim() || null,
        role:             r.role,
        phone_number:     r.phone_number || null,
        hr_system_id_adp: r.hr_system_id_adp.trim() || null,
      }));
      const res = await axiosClient.post<ImportResult[]>('/employees/bulk', payload);
      setResults(res.data);
      setStep('results');
      const anyCreated = res.data.some(r => r.status === 'created');
      if (anyCreated) onComplete();
    } catch (e: any) {
      // Surface top-level API errors (e.g. 400 too many rows) back in preview
      alert(e?.response?.data?.detail ?? 'Import failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleImportMore = () => {
    setRows([]);
    setResults([]);
    setStep('upload');
  };

  const STEP_LABELS: Record<Step, string> = {
    upload:  'Upload File',
    preview: 'Preview & Verify',
    results: 'Import Results',
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <div className="bg-card w-full max-w-4xl max-h-[90vh] rounded-2xl border border-border shadow-xl flex flex-col animate-slide-up">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
          <div className="flex items-center gap-4">
            <h2 className="font-semibold text-foreground">Bulk Import Employees</h2>
            {/* Step indicator */}
            <div className="hidden sm:flex items-center gap-2 text-xs">
              {(['upload', 'preview', 'results'] as Step[]).map((s, i) => (
                <React.Fragment key={s}>
                  {i > 0 && <span className="text-muted-foreground">›</span>}
                  <span className={step === s ? 'text-primary font-medium' : 'text-muted-foreground'}>
                    {STEP_LABELS[s]}
                  </span>
                </React.Fragment>
              ))}
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost p-1.5">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Step content */}
        <div className="flex-1 overflow-hidden flex flex-col min-h-0">
          {step === 'upload' && (
            <UploadStep onParsed={handleParsed} onClose={onClose} />
          )}
          {step === 'preview' && (
            <PreviewStep
              rows={rows}
              onChange={setRows}
              onSubmit={handleSubmit}
              onBack={() => setStep('upload')}
              submitting={submitting}
            />
          )}
          {step === 'results' && (
            <ResultsStep
              results={results}
              onClose={onClose}
              onImportMore={handleImportMore}
            />
          )}
        </div>
      </div>
    </div>
  );
}
