/**
 * ADR-512: the DSP's stolen-package report, on the phone where it is filed.
 *
 * The DA files it; the truck's driver or captain reviews it, edits any field
 * and signs a copy that is theirs; dispatch and management compare the two on
 * web. Labels and order follow the owner's report. The copied text is built by
 * the server, so it is identical to web's.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, Share, Alert, ActivityIndicator, Platform,
} from 'react-native';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { Button, MIN_TARGET, tick } from '@components/ui/primitives';

const BASE = '/incidents/stolen-package';
const TBA_RE = /^TBA\d{12}$/;
const MAX_TBAS = 50;

// Mirrors StolenPackageIn in backend/app/routers/stolen_package_reports.py and
// StolenPackageFields in frontend/src/api/types.ts.
export type Fields = {
  incident_date: string;
  incident_time: string | null;
  incident_address: string;
  anchor_point_address: string | null;
  lmet_called: boolean;
  lmet_case_number: string | null;
  bike_locks_used: boolean;
  cart_cover_used: boolean;
  totes_stolen: number;
  cart_stolen: boolean;
  packages_stolen: number;
  tbas: string[];
  summary: string;
};
type Version = Fields & {
  version: 'da' | 'reviewer';
  author_name: string | null;
  da_name: string | null;
  signed_at: string | null;
  pi_cleared_at: string | null;
};
export type State = 'submitted' | 'verified' | 'needs_reverification' | 'accepted';
type Report = {
  incident_id: string;
  dsp: string | null;
  state: State;
  accepted_at: string | null;
  versions: Partial<Record<'da' | 'reviewer', Version>>;
  can_sign: boolean;
  can_reverify: boolean;
  can_edit_da: boolean;
};
type Prefill = {
  dsp: string | null;
  da: { id: string; name: string };
  anchor_point_address: string | null;
  reviewers: Array<{ id: string; name: string | null }>;
};
export type ToSign = { incident_id: string; incident_date: string; kind: 'sign' | 'reverify'; da_name: string | null; packages_stolen: number };

const ymd = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const hm = (d: Date) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;

/** "2:30 PM", "2:30pm", "14:30" or "1430" to "14:30"; null if unreadable. */
export function parseTime(raw: string): string | null {
  const m = raw.trim().toLowerCase().match(/^(\d{1,2}):?(\d{2})\s*(am|pm|a|p)?$/);
  if (!m) return null;
  let h = Number(m[1]); const min = Number(m[2]);
  const ap = m[3]?.[0];
  if (ap) { if (h < 1 || h > 12) return null; if (ap === 'p' && h !== 12) h += 12; if (ap === 'a' && h === 12) h = 0; }
  if (h > 23 || min > 59) return null;
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}
const showTime = (t: string | null) => {
  if (!t) return '';
  const [h, m] = t.split(':').map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
};

function emptyReport(): Fields {
  const now = new Date();
  // The owner's defaults: LMET N, bike locks Y, cart cover Y, cart stolen N.
  return {
    incident_date: ymd(now), incident_time: hm(now), incident_address: '',
    anchor_point_address: null, lmet_called: false, lmet_case_number: null,
    bike_locks_used: true, cart_cover_used: true, totes_stolen: 0, cart_stolen: false,
    packages_stolen: 0, tbas: [], summary: '',
  };
}
function fieldsOf(v: Version): Fields {
  return {
    incident_date: v.incident_date, incident_time: v.incident_time ? v.incident_time.slice(0, 5) : null,
    incident_address: v.incident_address ?? '', anchor_point_address: v.anchor_point_address,
    lmet_called: v.lmet_called, lmet_case_number: v.lmet_case_number,
    bike_locks_used: v.bike_locks_used, cart_cover_used: v.cart_cover_used,
    totes_stolen: v.totes_stolen, cart_stolen: v.cart_stolen, packages_stolen: v.packages_stolen,
    tbas: v.tbas ?? [], summary: v.summary,
  };
}

// ─── Y/N: a two-option radio group, 44pt targets ─────────────────────────────

function YesNo({ label, value, onChange }: { label: string; value: boolean; onChange: (v: boolean) => void }) {
  const c = useColors(); const s = styles(c);
  return (
    <View style={s.ynRow} accessibilityRole="radiogroup" accessibilityLabel={label}>
      <Text style={s.ynLabel}>{label}</Text>
      <View style={s.ynGroup}>
        {[true, false].map(v => (
          <TouchableOpacity key={String(v)} onPress={() => onChange(v)}
            accessibilityRole="radio" accessibilityState={{ checked: value === v }} accessibilityLabel={`${label} ${v ? 'Yes' : 'No'}`}
            style={[s.ynBtn, value === v && { backgroundColor: c.brand }]}>
            <Text style={[s.ynText, value === v && { color: c.brandForeground }]}>{v ? 'Yes' : 'No'}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

// ─── TBAs: typed or pasted, split the same way ───────────────────────────────

function TbaInput({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const c = useColors(); const s = styles(c);
  const [draft, setDraft] = useState('');
  const [bad, setBad] = useState<string[]>([]);
  const [full, setFull] = useState('');
  const commit = (raw: string) => {
    const tokens = raw.split(/[\s,;]+/).map(t => t.trim().toUpperCase()).filter(Boolean);
    if (!tokens.length) { setDraft(''); return; }
    const next = [...value];
    for (const t of tokens) if (TBA_RE.test(t) && !next.includes(t) && next.length < MAX_TBAS) next.push(t);
    const invalid = tokens.filter(t => !TBA_RE.test(t));
    const fresh = new Set(tokens.filter(t => TBA_RE.test(t) && !value.includes(t)));
    const overflow = fresh.size - (next.length - value.length);   // valid, new, past the cap
    setFull(overflow > 0 ? `Only ${MAX_TBAS} TBAs fit on one report; ${overflow} not added.` : '');
    onChange(next); setBad(invalid);
    setDraft(invalid.join(' '));   // keep what needs correcting
  };
  return (
    <View>
      <View style={[s.tbaBox, bad.length > 0 && { borderColor: c.danger }]}>
        {value.map(t => (
          <TouchableOpacity key={t} style={s.tbaChip} onPress={() => onChange(value.filter(x => x !== t))}
            accessibilityRole="button" accessibilityLabel={`Remove ${t}`}>
            <Text style={s.tbaText}>{t}  ✕</Text>
          </TouchableOpacity>
        ))}
        <TextInput value={draft} style={s.tbaInput} autoCapitalize="characters" autoCorrect={false}
          placeholder={value.length ? 'Add another' : 'TBA followed by 12 digits'} placeholderTextColor={c.placeholder}
          accessibilityLabel="Add a TBA"
          onChangeText={t => {
            setBad([]);
            // A paste or a typed separator commits; otherwise keep typing.
            if (/[\s,;]/.test(t)) commit(t); else setDraft(t);
          }}
          onSubmitEditing={() => commit(draft)} onBlur={() => commit(draft)} blurOnSubmit={false} returnKeyType="next" />
      </View>
      {!!full && <Text style={[s.err, { color: c.warning }]}>{full}</Text>}
      {bad.length > 0 && <Text style={s.err}>Not a TBA: {bad.join(', ')}. A TBA is TBA followed by 12 digits.</Text>}
    </View>
  );
}

// ─── The form ────────────────────────────────────────────────────────────────

export type FormMode = 'file' | 'edit' | 'sign' | 'reverify';

export function StolenPackageForm({ mode, incidentId, initial, daName, onDone, onCancel }: {
  mode: FormMode; incidentId?: string; initial?: Fields; daName?: string | null;
  onDone: (msg: string) => void; onCancel?: () => void;
}) {
  const c = useColors(); const s = styles(c);
  const [f, setF] = useState<Fields>(initial ?? emptyReport());
  const [timeText, setTimeText] = useState(showTime((initial ?? f).incident_time));
  const [comments, setComments] = useState('');
  const [prefill, setPrefill] = useState<Prefill | null>(null);
  const [saving, setSaving] = useState(false);
  const anchorTouched = useRef(!!initial?.anchor_point_address);
  const set = <K extends keyof Fields>(k: K, v: Fields[K]) => setF(p => ({ ...p, [k]: v }));

  const today = new Date(); const yesterday = new Date(Date.now() - 86_400_000);
  const dates = Array.from(new Set([ymd(today), ymd(yesterday), f.incident_date]));

  useEffect(() => {
    if (mode !== 'file') return;
    const params: Record<string, string> = { incident_date: f.incident_date };
    if (f.incident_time) params.incident_time = f.incident_time;
    apiClient.get(`${BASE}/prefill`, { params })
      .then(r => {
        setPrefill(r.data);
        if (!anchorTouched.current) setF(p => ({ ...p, anchor_point_address: r.data.anchor_point_address }));
      })
      .catch(() => { /* the fields stay editable by hand */ });
  }, [mode, f.incident_date, f.incident_time]);

  const submit = async () => {
    if (timeText.trim() && !parseTime(timeText)) { Alert.alert('Time of incident', 'Enter a time like 2:30 PM.'); return; }
    if (!f.incident_address.trim()) { Alert.alert('Required', 'Enter the incident address.'); return; }
    if (!f.summary.trim()) { Alert.alert('Required', 'Write the incident summary.'); return; }
    setSaving(true);
    const body = { ...f, incident_time: timeText.trim() ? parseTime(timeText) : null,
      incident_address: f.incident_address.trim(), summary: f.summary.trim(),
      lmet_case_number: f.lmet_called ? (f.lmet_case_number || null) : null };
    try {
      if (mode === 'file') {
        const r = await apiClient.post(BASE, body);
        tick();
        onDone(r.data.reviewers_notified === 0
          ? 'Report signed and filed. No driver or captain is on your truck today, so dispatch will arrange the verification.'
          : `Report signed and filed. ${r.data.reviewers_notified === 1 ? 'Your driver has' : 'Your driver and captain have'} been asked to verify it.`);
      } else if (mode === 'edit') {
        await apiClient.put(`${BASE}/${incidentId}/da`, body);
        tick(); onDone('Report signed and saved.');
      } else if (mode === 'reverify') {
        await apiClient.put(`${BASE}/${incidentId}/reviewer`, { ...body, reviewer_comments: comments.trim() || null });
        tick(); onDone('Report verified again.');
      } else {
        await apiClient.post(`${BASE}/${incidentId}/sign`, { ...body, reviewer_comments: comments.trim() || null });
        tick(); onDone('Report verified and signed.');
      }
    } catch (err: unknown) {
      Alert.alert('Not saved', errorText(err, 'Could not save the report. Try again.'));
    } finally {
      setSaving(false);
    }
  };

  const input = [s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.card }];
  return (
    <View>
      {mode === 'sign' && (
        <Text style={s.note}>This is {daName ?? 'the DA'}'s report. Correct anything that is off, then verify and sign. The verified copy is yours.</Text>
      )}
      {mode === 'reverify' && (
        <Text style={[s.note, { backgroundColor: c.warningLight }]}>{daName ?? 'The DA'} changed their report. Their new version is below. Correct anything that is off, then verify it again.</Text>
      )}
      <View style={s.pairRow}>
        <View style={s.pairCell}><Text style={s.label}>DSP</Text><Text style={s.value}>{prefill?.dsp ?? (mode === 'file' ? '…' : 'From company settings')}</Text></View>
        <View style={s.pairCell}><Text style={s.label}>DA Name</Text><Text style={s.value}>{(mode === 'file' ? prefill?.da.name : daName) ?? '…'}</Text></View>
      </View>

      <Text style={s.label}>Date of incident</Text>
      <View style={s.chipRow}>
        {dates.map(d => (
          <TouchableOpacity key={d} onPress={() => set('incident_date', d)} accessibilityRole="radio"
            accessibilityState={{ checked: f.incident_date === d }}
            style={[s.chip, f.incident_date === d && { backgroundColor: c.brand, borderColor: c.brand }]}>
            <Text style={[s.chipText, f.incident_date === d && { color: c.brandForeground }]}>
              {d === ymd(today) ? 'Today' : d === ymd(yesterday) ? 'Yesterday' : new Date(`${d}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <Text style={s.label}>Time of incident</Text>
      <TextInput style={input} value={timeText} placeholder="e.g. 2:30 PM" placeholderTextColor={c.placeholder}
        onChangeText={setTimeText}
        onBlur={() => { const t = parseTime(timeText); if (t) { set('incident_time', t); setTimeText(showTime(t)); } }} />

      <Text style={s.label}>Incident Address *</Text>
      <TextInput style={input} value={f.incident_address} maxLength={200} placeholder="Where the theft happened"
        placeholderTextColor={c.placeholder} onChangeText={v => set('incident_address', v)} />
      <Text style={s.hint}>A customer address. Cleared from the report after 60 days.</Text>

      <Text style={s.label}>Anchor Point Address</Text>
      <TextInput style={input} value={f.anchor_point_address ?? ''} maxLength={255}
        placeholder="Filled from the truck's anchor point" placeholderTextColor={c.placeholder}
        onChangeText={v => { anchorTouched.current = true; set('anchor_point_address', v || null); }} />

      <View style={s.group}>
        <YesNo label="Was LMET called?" value={f.lmet_called} onChange={v => set('lmet_called', v)} />
        {f.lmet_called && (
          <TextInput style={input} value={f.lmet_case_number ?? ''} maxLength={64} placeholder="LMET case number"
            placeholderTextColor={c.placeholder} onChangeText={v => set('lmet_case_number', v || null)} />
        )}
        <YesNo label="Were bike locks used to anchor totes?" value={f.bike_locks_used} onChange={v => set('bike_locks_used', v)} />
        <YesNo label="Was a cart cover being used?" value={f.cart_cover_used} onChange={v => set('cart_cover_used', v)} />
        <YesNo label="Was the cart stolen?" value={f.cart_stolen} onChange={v => set('cart_stolen', v)} />
      </View>

      <View style={s.pairRow}>
        <View style={s.pairCell}>
          <Text style={s.label}>Totes stolen</Text>
          <TextInput style={input} keyboardType="number-pad" value={String(f.totes_stolen)}
            onChangeText={v => set('totes_stolen', Math.min(50, Number(v.replace(/\D/g, '')) || 0))} />
        </View>
        <View style={s.pairCell}>
          <Text style={s.label}>Packages stolen</Text>
          <TextInput style={input} keyboardType="number-pad" value={String(f.packages_stolen)}
            onChangeText={v => set('packages_stolen', Math.min(500, Number(v.replace(/\D/g, '')) || 0))} />
        </View>
      </View>
      {f.tbas.length > 0 && f.tbas.length !== f.packages_stolen && (
        <Text style={[s.hint, { color: c.warning }]}>{f.tbas.length} TBA{f.tbas.length === 1 ? '' : 's'} listed for {f.packages_stolen} stolen package{f.packages_stolen === 1 ? '' : 's'}.</Text>
      )}

      <Text style={s.label}>TBAs stolen</Text>
      <TbaInput value={f.tbas} onChange={v => set('tbas', v)} />

      <Text style={s.label}>Incident Summary *</Text>
      <TextInput style={[input, s.area]} value={f.summary} maxLength={2000} multiline textAlignVertical="top"
        placeholder="What happened, in order" placeholderTextColor={c.placeholder} onChangeText={v => set('summary', v)} />

      {(mode === 'sign' || mode === 'reverify') && (
        <>
          <Text style={s.label}>Additional comments</Text>
          <TextInput style={[input, s.area]} value={comments} maxLength={2000} multiline textAlignVertical="top"
            onChangeText={setComments} />
          <Text style={s.hint}>
            Only dispatch and management see this. It is not part of the copied report.
            {mode === 'reverify' ? ' Your earlier comments stay on file; anything you write here is added to them.' : ''}
          </Text>
        </>
      )}

      <View style={s.actions}>
        {onCancel && <View style={s.grow}><Button variant="secondary" fullWidth onPress={onCancel}>Cancel</Button></View>}
        <View style={s.grow}>
          <Button fullWidth loading={saving} disabled={saving} onPress={submit}>
            {{ file: 'Sign and file', edit: 'Sign and save', sign: 'Verify and sign', reverify: 'Verify again' }[mode]}
          </Button>
        </View>
      </View>
    </View>
  );
}

// ─── Copy report: the share sheet carries Copy on both platforms ─────────────

async function shareReport(incidentId: string) {
  try {
    const r = await apiClient.get(`${BASE}/${incidentId}/report-text`, { responseType: 'text' });
    await Share.share({ message: String(r.data) });
  } catch (err: unknown) {
    Alert.alert('Not available', errorText(err, 'Could not load the report text.'));
  }
}

// ─── The report: what this person may do with it ─────────────────────────────

export function StolenPackageReportView({ incidentId, onChanged }: { incidentId: string; onChanged?: () => void }) {
  const c = useColors(); const s = styles(c);
  const [rep, setRep] = useState<Report | null>(null);
  const [missing, setMissing] = useState(false);
  const [mode, setMode] = useState<FormMode | null>(null);
  const [notice, setNotice] = useState('');

  const load = useCallback(() => {
    apiClient.get(`${BASE}/${incidentId}`).then(r => setRep(r.data)).catch(() => setMissing(true));
  }, [incidentId]);
  useEffect(load, [load]);

  if (missing) return null;   // filed before ADR-512: no report rows
  if (!rep) return <ActivityIndicator color={c.primary} />;
  const da = rep.versions.da; const rv = rep.versions.reviewer;
  const shown = rv ?? da;
  if (!shown || !da) return null;

  if (mode) {
    return (
      <StolenPackageForm mode={mode} incidentId={incidentId} daName={da.da_name} initial={fieldsOf(da)}
        onCancel={() => setMode(null)}
        onDone={msg => { setMode(null); setNotice(msg); load(); onChanged?.(); }} />
    );
  }

  const rows: Array<[string, string]> = [
    ['Address', shown.pi_cleared_at ? 'Cleared after 60 days' : (shown.incident_address || 'blank')],
    ['Time', showTime(shown.incident_time) || 'blank'],
    ['Packages', String(shown.packages_stolen)],
    ['TBAs', shown.tbas.length ? shown.tbas.join(', ') : (shown.pi_cleared_at ? 'Cleared after 60 days' : 'none')],
  ];
  return (
    <View>
      {!!notice && <Text style={[s.hint, { color: c.success }]}>{notice}</Text>}
      <StateLine state={rep.state} verifier={rv?.author_name ?? null} />
      {rows.map(([k, v]) => (
        <View key={k} style={s.kv}><Text style={s.k}>{k}</Text><Text style={s.v}>{v}</Text></View>
      ))}
      <View style={s.actions}>
        {rep.can_sign && <View style={s.grow}><Button fullWidth onPress={() => setMode('sign')}>Review and verify</Button></View>}
        {rep.can_reverify && <View style={s.grow}><Button fullWidth onPress={() => setMode('reverify')}>Verify again</Button></View>}
        {rep.can_edit_da && <View style={s.grow}><Button variant="secondary" fullWidth onPress={() => setMode('edit')}>Edit and sign again</Button></View>}
        <View style={s.grow}><Button variant="outline" fullWidth onPress={() => shareReport(incidentId)}>Copy report</Button></View>
      </View>
    </View>
  );
}

export function StateLine({ state, verifier }: { state: State; verifier: string | null }) {
  const c = useColors(); const s = styles(c);
  const who = verifier ?? 'the driver or captain';
  const [text, color] = {
    submitted:            ['Waiting for verification', c.warning],
    verified:             [`Verified by ${who}`, c.info],
    needs_reverification: [`DA changed it. Waiting for ${who} to verify again`, c.warning],
    accepted:             ['Accepted', c.success],
  }[state];
  return <Text style={[s.status, { color }]}>{text}</Text>;
}

// ─── Reports waiting for this person's signature ─────────────────────────────

export function ReportsToSign({ refreshKey, onSigned }: { refreshKey: number; onSigned: () => void }) {
  const c = useColors(); const s = styles(c);
  const [rows, setRows] = useState<ToSign[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    apiClient.get(`${BASE}/to-sign`).then(r => setRows(r.data ?? [])).catch(() => setRows([]));
  }, [refreshKey]);
  if (!rows.length) return null;
  return (
    <View style={s.signCard}>
      <Text style={s.signTitle}>Reports to verify</Text>
      {rows.map(r => (
        <View key={r.incident_id} style={s.signRow}>
          <TouchableOpacity style={s.signHead} onPress={() => setOpen(open === r.incident_id ? null : r.incident_id)}
            accessibilityRole="button" accessibilityState={{ expanded: open === r.incident_id }}>
            <Text style={s.signName}>{r.kind === 'reverify' ? 'Changed, verify again' : 'Stolen packages'}: {r.da_name ?? 'DA'}</Text>
            <Text style={s.hint}>
              {new Date(`${r.incident_date}T12:00:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })} · {r.packages_stolen} pkg
            </Text>
          </TouchableOpacity>
          {open === r.incident_id && <StolenPackageReportView incidentId={r.incident_id} onChanged={onSigned} />}
        </View>
      ))}
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  label:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.foreground, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: spacing.xs, marginTop: spacing.sm },
  value:    { fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.foreground, minHeight: MIN_TARGET, textAlignVertical: 'center', paddingTop: spacing.sm },
  hint:     { fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: spacing.xs },
  note:     { fontSize: fontSize.sm, color: c.foreground, backgroundColor: c.infoLight, borderRadius: radius.md, padding: spacing.sm, marginBottom: spacing.sm },
  err:      { fontSize: fontSize.xs, color: c.danger, marginTop: spacing.xs },
  input:    { borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.sm, minHeight: MIN_TARGET, fontSize: fontSize.sm, marginBottom: spacing.xs },
  area:     { minHeight: 110, paddingTop: spacing.sm },
  pairRow:  { flexDirection: 'row', gap: spacing.sm },
  pairCell: { flex: 1 },
  grow:     { flex: 1 },
  chipRow:  { flexDirection: 'row', gap: spacing.xs, flexWrap: 'wrap' },
  chip:     { minHeight: MIN_TARGET, justifyContent: 'center', paddingHorizontal: spacing.md, borderRadius: radius.full, borderWidth: 1, borderColor: c.border, backgroundColor: c.card },
  chipText: { fontSize: fontSize.sm, color: c.foreground },
  group:    { borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm, marginTop: spacing.md, gap: spacing.xs },
  ynRow:    { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  ynLabel:  { flex: 1, fontSize: fontSize.sm, color: c.foreground },
  ynGroup:  { flexDirection: 'row', borderWidth: 1, borderColor: c.border, borderRadius: radius.md, overflow: 'hidden' },
  ynBtn:    { minWidth: 56, minHeight: MIN_TARGET, alignItems: 'center', justifyContent: 'center', backgroundColor: c.card },
  ynText:   { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.mutedForeground },
  tbaBox:   { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs, borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.xs, backgroundColor: c.card },
  tbaChip:  { minHeight: 36, justifyContent: 'center', paddingHorizontal: spacing.sm, borderRadius: radius.full, backgroundColor: c.surfaceMuted },
  tbaText:  { fontSize: fontSize.xs, color: c.foreground, fontFamily: Platform.select({ ios: 'Menlo', default: 'monospace' }) },
  tbaInput: { flexGrow: 1, minWidth: 160, minHeight: MIN_TARGET, fontSize: fontSize.sm, color: c.foreground },
  actions:  { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.md, marginBottom: spacing.sm },
  status:   { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, marginBottom: spacing.xs },
  kv:       { flexDirection: 'row', paddingVertical: 4, gap: spacing.sm },
  k:        { width: 80, fontSize: fontSize.xs, color: c.mutedForeground },
  v:        { flex: 1, fontSize: fontSize.sm, color: c.foreground },
  signCard: { backgroundColor: c.warningLight, borderRadius: radius.lg, padding: spacing.md, marginBottom: spacing.lg },
  signTitle:{ fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground, marginBottom: spacing.xs },
  signRow:  { backgroundColor: c.card, borderRadius: radius.md, padding: spacing.sm, marginTop: spacing.xs },
  signHead: { minHeight: MIN_TARGET, justifyContent: 'center' },
  signName: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground },
});
