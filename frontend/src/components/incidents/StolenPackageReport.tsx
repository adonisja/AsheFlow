// ADR-512: the DSP's stolen-package report. The DA files it; the truck's driver
// or captain reviews, edits and signs a copy; dispatch and management see where
// the two disagree. Field order and labels follow the owner's report exactly.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle, Copy, PenLine, X } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import { errorText } from '../../utils/errorText';
import { formatDateShort, getLocalYMD } from '../../utils/date';
import { FIELD_LABELS, MAX_TBAS, TBA_RE, displayValue, emptyReport, fieldsOf, splitTbas } from '../../utils/stolenPackage';
import type {
  StolenPackageFields, StolenPackageFiled, StolenPackagePrefill,
  StolenPackageReport, StolenPackageToSign,
} from '../../api/types';

const BASE = '/incidents/stolen-package';
const inputCls = 'w-full min-h-[44px] p-2.5 rounded-xl border border-border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50';
const labelCls = 'block text-xs font-semibold text-subtle uppercase tracking-wider mb-1';

// ---------------------------------------------------------------------------
// Y/N: a two-option radio group drawn as a segmented control, 44px targets.
// ---------------------------------------------------------------------------

function YesNo({ label, value, onChange, disabled }: {
  label: string; value: boolean; onChange: (v: boolean) => void; disabled?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span id={`yn-${label}`} className="text-sm text-foreground">{label}</span>
      <div role="radiogroup" aria-labelledby={`yn-${label}`} className="flex shrink-0 rounded-xl border border-border overflow-hidden">
        {[true, false].map(v => (
          <button key={String(v)} type="button" role="radio" aria-checked={value === v} disabled={disabled}
            onClick={() => onChange(v)}
            className={`min-w-[56px] min-h-[44px] text-sm font-semibold transition-colors disabled:opacity-60
              ${value === v ? 'bg-primary text-primary-foreground' : 'bg-background text-muted-foreground hover:bg-accent/40'}`}>
            {v ? 'Yes' : 'No'}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// TBAs: a token input. Typing and pasting split the same way.
// ---------------------------------------------------------------------------

function TbaInput({ value, onChange, disabled }: {
  value: string[]; onChange: (v: string[]) => void; disabled?: boolean;
}) {
  const [draft, setDraft] = useState('');
  const [status, setStatus] = useState('');
  const [bad, setBad] = useState<string[]>([]);
  const [full, setFull] = useState('');

  const commit = (raw: string) => {
    const tokens = splitTbas(raw);
    if (!tokens.length) return;
    const good = tokens.filter(t => TBA_RE.test(t));
    const invalid = tokens.filter(t => !TBA_RE.test(t));
    const next = [...value];
    for (const t of good) if (!next.includes(t) && next.length < MAX_TBAS) next.push(t);
    const added = next.length - value.length;
    const fresh = new Set(good.filter(t => !value.includes(t)));
    const overflow = fresh.size - added;   // valid, new, but past the cap
    onChange(next);
    setBad(invalid);
    setFull(overflow > 0 ? `Only ${MAX_TBAS} TBAs fit on one report; ${overflow} not added.` : '');
    // Invalid entries stay in the box so they can be corrected, not retyped.
    setDraft(invalid.join(' '));
    setStatus(added ? `Added ${added} TBA${added === 1 ? '' : 's'}.` : '');
  };

  return (
    <div>
      <div className={`flex flex-wrap gap-1.5 p-2 rounded-xl border bg-background ${bad.length ? 'border-danger' : 'border-border'}`}>
        {value.map(t => (
          <span key={t} className="inline-flex items-center gap-1 pl-2.5 pr-1 py-1 rounded-full bg-accent/50 text-xs font-mono text-foreground">
            {t}
            {!disabled && (
              <button type="button" aria-label={`Remove ${t}`} onClick={() => onChange(value.filter(x => x !== t))}
                className="p-1 rounded-full hover:bg-danger/15">
                <X className="w-3 h-3" />
              </button>
            )}
          </span>
        ))}
        {!disabled && (
          <input value={draft} aria-label="Add a TBA" placeholder={value.length ? 'Add another' : 'TBA followed by 12 digits'}
            className="flex-1 min-w-[160px] min-h-[36px] bg-transparent text-sm font-mono focus:outline-none"
            onChange={e => { setBad([]); setDraft(e.target.value); }}
            onPaste={e => { e.preventDefault(); commit(draft + ' ' + e.clipboardData.getData('text')); }}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ',' || e.key === ' ') { e.preventDefault(); commit(draft); }
              else if (e.key === 'Backspace' && !draft && value.length) onChange(value.slice(0, -1));
            }}
            onBlur={() => commit(draft)} />
        )}
      </div>
      {full && <p className="text-xs text-warning mt-1">{full}</p>}
      {bad.length > 0 && <p className="text-xs text-danger mt-1">Not a TBA: {bad.join(', ')}. A TBA is TBA followed by 12 digits.</p>}
      <p className="sr-only" aria-live="polite">{status}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The form: filing (DA), editing the DA's version, or signing (reviewer).
// ---------------------------------------------------------------------------

export type FormMode = 'file' | 'edit' | 'sign';

export function StolenPackageForm({ mode, incidentId, initial, daName, onDone, onCancel }: {
  mode: FormMode;
  incidentId?: string;
  initial?: StolenPackageFields;
  daName?: string | null;
  onDone: (msg: string) => void;
  onCancel?: () => void;
}) {
  const [f, setF] = useState<StolenPackageFields>(initial ?? emptyReport());
  const [comments, setComments] = useState('');
  const [prefill, setPrefill] = useState<StolenPackagePrefill | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  // Autofill the anchor point until the person types their own.
  const anchorTouched = useRef(!!initial?.anchor_point_address);

  const set = <K extends keyof StolenPackageFields>(k: K, v: StolenPackageFields[K]) => setF(p => ({ ...p, [k]: v }));

  useEffect(() => {
    if (mode !== 'file') return;
    const params: Record<string, string> = { incident_date: f.incident_date };
    if (f.incident_time) params.incident_time = f.incident_time;
    axiosClient.get<StolenPackagePrefill>(`${BASE}/prefill`, { params })
      .then(r => {
        setPrefill(r.data);
        if (!anchorTouched.current) setF(p => ({ ...p, anchor_point_address: r.data.anchor_point_address }));
      })
      .catch(e => console.error('Stolen-package prefill failed:', e));
  }, [mode, f.incident_date, f.incident_time]);

  const submit = async () => {
    if (!f.incident_address.trim()) return setError('Enter the incident address.');
    if (!f.summary.trim()) return setError('Write the incident summary.');
    setError(''); setSaving(true);
    const body = { ...f, incident_address: f.incident_address.trim(), summary: f.summary.trim(),
      lmet_case_number: f.lmet_called ? (f.lmet_case_number || null) : null };
    try {
      if (mode === 'file') {
        const r = await axiosClient.post<StolenPackageFiled>(BASE, body);
        onDone(r.data.review_required
          ? `Report filed. ${r.data.reviewers_notified === 1 ? 'Your driver has' : 'Your driver and captain have'} been asked to sign it.`
          : 'Report filed.');
        setF(emptyReport()); anchorTouched.current = false;
      } else if (mode === 'edit') {
        await axiosClient.put(`${BASE}/${incidentId}/da`, body);
        onDone('Report updated.');
      } else {
        await axiosClient.post(`${BASE}/${incidentId}/sign`, { ...body, reviewer_comments: comments.trim() || null });
        onDone('Report signed.');
      }
    } catch (err: unknown) {
      setError(errorText(err, 'Could not save the report. Try again.'));
    } finally {
      setSaving(false);
    }
  };

  const shownDa = mode === 'file' ? prefill?.da.name : daName;

  return (
    <div className="space-y-4">
      {mode === 'sign' && (
        <p className="text-sm text-foreground p-3 rounded-xl bg-info/10 border border-info/20">
          This is {daName ?? 'the DA'}&apos;s report. Correct anything that is off, then sign. The signed copy is yours.
        </p>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <span className={labelCls}>DSP</span>
          <p className="text-sm font-medium text-foreground min-h-[44px] flex items-center">{prefill?.dsp ?? (mode === 'file' ? '…' : 'From company settings')}</p>
        </div>
        <div>
          <span className={labelCls}>DA Name</span>
          <p className="text-sm font-medium text-foreground min-h-[44px] flex items-center">{shownDa ?? '…'}</p>
        </div>
        <div>
          <label htmlFor="sp-date" className={labelCls}>{FIELD_LABELS.incident_date}</label>
          <input id="sp-date" type="date" value={f.incident_date} max={getLocalYMD()}
            onChange={e => set('incident_date', e.target.value)} className={inputCls} />
        </div>
        <div>
          <label htmlFor="sp-time" className={labelCls}>{FIELD_LABELS.incident_time}</label>
          <input id="sp-time" type="time" value={f.incident_time ?? ''}
            onChange={e => set('incident_time', e.target.value || null)} className={inputCls} />
        </div>
      </div>

      <div>
        <label htmlFor="sp-addr" className={labelCls}>{FIELD_LABELS.incident_address} *</label>
        <input id="sp-addr" value={f.incident_address} maxLength={200} autoComplete="off"
          onChange={e => set('incident_address', e.target.value)} placeholder="Where the theft happened" className={inputCls} />
        <p className="text-xs text-subtle mt-1">A customer address. Cleared from the report after 60 days.</p>
      </div>
      <div>
        <label htmlFor="sp-ap" className={labelCls}>{FIELD_LABELS.anchor_point_address}</label>
        <input id="sp-ap" value={f.anchor_point_address ?? ''} maxLength={255}
          onChange={e => { anchorTouched.current = true; set('anchor_point_address', e.target.value || null); }}
          placeholder="Filled from the truck's anchor point" className={inputCls} />
      </div>

      <div className="space-y-2 p-3 rounded-xl border border-border">
        <YesNo label={FIELD_LABELS.lmet_called} value={f.lmet_called} onChange={v => set('lmet_called', v)} />
        {f.lmet_called && (
          <div>
            <label htmlFor="sp-lmet" className={labelCls}>{FIELD_LABELS.lmet_case_number}</label>
            <input id="sp-lmet" value={f.lmet_case_number ?? ''} maxLength={64}
              onChange={e => set('lmet_case_number', e.target.value || null)} className={inputCls} />
          </div>
        )}
        <YesNo label={FIELD_LABELS.bike_locks_used} value={f.bike_locks_used} onChange={v => set('bike_locks_used', v)} />
        <YesNo label={FIELD_LABELS.cart_cover_used} value={f.cart_cover_used} onChange={v => set('cart_cover_used', v)} />
        <YesNo label={FIELD_LABELS.cart_stolen} value={f.cart_stolen} onChange={v => set('cart_stolen', v)} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="sp-totes" className={labelCls}>Totes stolen</label>
          <input id="sp-totes" type="number" inputMode="numeric" min={0} max={50} value={f.totes_stolen}
            onChange={e => set('totes_stolen', Math.max(0, Math.min(50, Number(e.target.value) || 0)))} className={inputCls} />
        </div>
        <div>
          <label htmlFor="sp-pkgs" className={labelCls}>Packages stolen</label>
          <input id="sp-pkgs" type="number" inputMode="numeric" min={0} max={500} value={f.packages_stolen}
            onChange={e => set('packages_stolen', Math.max(0, Math.min(500, Number(e.target.value) || 0)))} className={inputCls} />
        </div>
      </div>
      {f.tbas.length > 0 && f.tbas.length !== f.packages_stolen && (
        <p className="text-xs text-warning">{f.tbas.length} TBA{f.tbas.length === 1 ? '' : 's'} listed for {f.packages_stolen} stolen package{f.packages_stolen === 1 ? '' : 's'}.</p>
      )}

      <div>
        <span className={labelCls}>{FIELD_LABELS.tbas}</span>
        <TbaInput value={f.tbas} onChange={v => set('tbas', v)} />
      </div>

      <div>
        <label htmlFor="sp-sum" className={labelCls}>{FIELD_LABELS.summary} *</label>
        <textarea id="sp-sum" value={f.summary} maxLength={2000} rows={4}
          onChange={e => set('summary', e.target.value)} placeholder="What happened, in order"
          className={`${inputCls} resize-y`} />
      </div>

      {mode === 'sign' && (
        <div>
          <label htmlFor="sp-comments" className={labelCls}>Additional comments</label>
          <textarea id="sp-comments" value={comments} maxLength={2000} rows={3}
            onChange={e => setComments(e.target.value)} className={`${inputCls} resize-y`} />
          <p className="text-xs text-subtle mt-1">Only dispatch and management see this. It is not part of the copied report.</p>
        </div>
      )}

      {error && <p role="alert" className="text-xs text-danger">{error}</p>}
      <div className="flex gap-2">
        {onCancel && <button type="button" onClick={onCancel} className="btn-secondary flex-1 min-h-[44px]">Cancel</button>}
        <button type="button" onClick={submit} disabled={saving} className="btn-primary flex-1 min-h-[44px] disabled:opacity-50">
          {saving ? 'Saving…' : mode === 'file' ? 'File report' : mode === 'edit' ? 'Save changes' : 'Sign report'}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Copy report: server-built text in the owner's layout (ADR-512 D6).
// ---------------------------------------------------------------------------

export function CopyReportButton({ incidentId }: { incidentId: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'manual'>('idle');
  const [text, setText] = useState('');
  const copy = async () => {
    try {
      const r = await axiosClient.get<string>(`${BASE}/${incidentId}/report-text`, { responseType: 'text' });
      setText(r.data);
      try {
        await navigator.clipboard.writeText(r.data);
        setState('copied');
        window.setTimeout(() => setState('idle'), 2500);
      } catch {
        // Clipboard denied (insecure origin, permissions): show the text to select.
        setState('manual');
      }
    } catch (e) {
      console.error('Report text failed:', e);
    }
  };
  return (
    <div className="space-y-2">
      <button type="button" onClick={copy} className="btn-secondary text-xs min-h-[44px] inline-flex items-center gap-1.5">
        {state === 'copied' ? <CheckCircle className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
        {state === 'copied' ? 'Copied' : 'Copy report'}
      </button>
      {state === 'manual' && (
        <textarea readOnly value={text} rows={15} aria-label="Report text" onFocus={e => e.currentTarget.select()}
          className="w-full p-2.5 rounded-xl border border-border bg-background text-xs font-mono" />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The report: both versions, mismatches (oversight), and the actions the
// server says this person may take.
// ---------------------------------------------------------------------------

export function StolenPackageReportView({ incidentId, onChanged }: { incidentId: string; onChanged?: () => void }) {
  const [rep, setRep] = useState<StolenPackageReport | null>(null);
  const [mode, setMode] = useState<FormMode | null>(null);
  const [notice, setNotice] = useState('');
  const [missing, setMissing] = useState(false);

  const load = useCallback(() => {
    axiosClient.get<StolenPackageReport>(`${BASE}/${incidentId}`)
      .then(r => setRep(r.data))
      .catch(() => setMissing(true));
  }, [incidentId]);
  useEffect(load, [load]);

  // A stolen-packages incident filed before ADR-512 has no report rows.
  if (missing) return null;
  if (!rep) return <p className="text-xs text-subtle">Loading report…</p>;

  const da = rep.versions.da;
  const rv = rep.versions.reviewer;
  const shown = rv ?? da;
  if (!shown) return null;

  if (mode && da) {
    return (
      <StolenPackageForm mode={mode} incidentId={incidentId} daName={da.da_name}
        initial={fieldsOf(da)}
        onCancel={() => setMode(null)}
        onDone={msg => { setMode(null); setNotice(msg); load(); onChanged?.(); }} />
    );
  }

  const mismatched = new Set(rep.mismatches.map(m => m.field));
  const keys = Object.keys(FIELD_LABELS) as (keyof StolenPackageFields)[];

  return (
    <div className="space-y-3">
      {notice && <p role="status" className="text-xs text-success">{notice}</p>}
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {rv
          ? <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-success/15 text-success font-semibold"><CheckCircle className="w-3 h-3" />Signed by {rv.author_name ?? 'reviewer'}</span>
          : <span className="px-2 py-0.5 rounded-full bg-warning/15 text-warning font-semibold">Waiting for the driver or captain to sign</span>}
        {rep.mismatches.length > 0 && (
          <span className="px-2 py-0.5 rounded-full bg-danger/15 text-danger font-semibold">
            {rep.mismatches.length} difference{rep.mismatches.length === 1 ? '' : 's'} between versions
          </span>
        )}
        {shown.pi_cleared_at && <span className="text-subtle">Address and TBAs cleared after 60 days.</span>}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-subtle">
              <th className="py-1 pr-3 font-semibold">Field</th>
              <th className="py-1 pr-3 font-semibold">{rv ? `DA (${da?.author_name ?? 'DA'})` : 'Report'}</th>
              {rv && <th className="py-1 font-semibold">Signed ({rv.author_name ?? 'reviewer'})</th>}
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-border/50"><td className="py-1.5 pr-3 text-subtle">DSP</td><td className="py-1.5 pr-3" colSpan={rv ? 2 : 1}>{rep.dsp ?? 'blank'}</td></tr>
            <tr className="border-t border-border/50"><td className="py-1.5 pr-3 text-subtle">DA Name</td><td className="py-1.5 pr-3" colSpan={rv ? 2 : 1}>{shown.da_name ?? 'blank'}</td></tr>
            {keys.map(k => {
              const diff = mismatched.has(k);
              return (
                <tr key={k} className={`border-t border-border/50 ${diff ? 'bg-danger/10' : ''}`}>
                  <td className="py-1.5 pr-3 text-subtle align-top">{FIELD_LABELS[k]}{diff && <span className="sr-only"> (differs)</span>}</td>
                  <td className={`py-1.5 pr-3 align-top whitespace-pre-wrap break-words ${diff ? 'text-danger font-semibold' : 'text-foreground'}`}>{displayValue(k, da?.[k])}</td>
                  {rv && <td className={`py-1.5 align-top whitespace-pre-wrap break-words ${diff ? 'text-danger font-semibold' : 'text-foreground'}`}>{displayValue(k, rv[k])}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {rv?.reviewer_comments && (
        <div className="p-3 rounded-xl bg-accent/30 border border-border">
          <p className="text-xs font-semibold text-subtle uppercase tracking-wider mb-1">Additional comments from {rv.author_name ?? 'the reviewer'}</p>
          <p className="text-sm text-foreground whitespace-pre-wrap">{rv.reviewer_comments}</p>
          <p className="text-xs text-subtle mt-1">Visible to dispatch and management only. Not in the copied report.</p>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {rep.can_sign && (
          <button type="button" onClick={() => setMode('sign')} className="btn-primary text-xs min-h-[44px] inline-flex items-center gap-1.5">
            <PenLine className="w-3.5 h-3.5" /> Review and sign
          </button>
        )}
        {rep.can_edit_da && (
          <button type="button" onClick={() => setMode('edit')} className="btn-secondary text-xs min-h-[44px]">Edit DA report</button>
        )}
        <CopyReportButton incidentId={incidentId} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reports waiting for this person's signature (the notification's target).
// ---------------------------------------------------------------------------

export function ReportsToSign({ refreshKey, onSigned }: { refreshKey: number; onSigned: () => void }) {
  const [rows, setRows] = useState<StolenPackageToSign[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    axiosClient.get<StolenPackageToSign[]>(`${BASE}/to-sign`)
      .then(r => setRows(r.data))
      .catch(e => console.error('Reports to sign failed:', e));
  }, [refreshKey]);
  if (!rows.length) return null;
  return (
    <div className="card space-y-3 border-warning/40">
      <h2 className="section-title">Reports to sign</h2>
      {rows.map(r => (
        <div key={r.incident_id} className="rounded-xl border border-border bg-background p-3 space-y-3">
          <button type="button" onClick={() => setOpen(open === r.incident_id ? null : r.incident_id)}
            className="w-full min-h-[44px] flex items-center justify-between text-left">
            <span className="text-sm font-medium text-foreground">Stolen packages: {r.da_name ?? 'DA'}</span>
            <span className="text-xs text-subtle">{formatDateShort(r.incident_date)} · {r.packages_stolen} package{r.packages_stolen === 1 ? '' : 's'}</span>
          </button>
          {open === r.incident_id && <StolenPackageReportView incidentId={r.incident_id} onChanged={onSigned} />}
        </div>
      ))}
    </div>
  );
}

