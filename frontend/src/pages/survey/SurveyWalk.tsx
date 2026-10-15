/**
 * One walk of one block (ADR-504): the city's doors, and a form per door.
 *
 * Form version 2 (ADR-504 D8), from the usage analysis of the old form and the
 * owner's edits:
 *   [A] "also receives for": only doors on the same city block are offered;
 *   [B] up to three delivery points; "which side" is pre-filled with the door's
 *       own street and offers the streets its block faces, in the owner's order;
 *   [C] hours by day group (weekdays / Saturday / Sunday);
 *   [D] each unit or one drop point, pre-filled from the building type;
 *   [E] "didn't find out" is an answer, and the default;
 *   [F] a door that is not a delivery point is recorded as such.
 *
 * ADR-511: the form is used standing on a sidewalk, one-handed, and is
 * interrupted all the time. So it is three steps rather than one long page,
 * every answer is kept as a local draft until the door is saved, and every
 * touch target is at least 44px.
 */
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Check, ChevronLeft, ChevronRight, Loader2, Plus, X } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../../components/ui/ErrorBanner';
import ConfirmDialog from '../../components/ui/ConfirmDialog';
import SelectMenu, { type SelectOption } from '../../components/ui/SelectMenu';
import { useReducedMotion } from '../../hooks/useReducedMotion';
import { errorText } from '../../utils/errorText';
import { BUILDING_TYPES } from '../../utils/addressProfile';
import type {
  SurveyAddress, SurveyDayHours, SurveyDeliveryMode, SurveyDeliveryPoint, SurveyDeliveryPointIn,
  SurveyObservationIn, SurveySource, SurveyTri, SurveyWalk,
} from '../../api/types';

const SOURCES: { value: SurveySource; label: string }[] = [
  { value: 'observed', label: 'I saw it' },
  { value: 'front_desk', label: 'Front desk' },
  { value: 'mailroom', label: 'Mailroom' },
  { value: 'security', label: 'Security' },
];
const POINTS: { value: SurveyDeliveryPoint; label: string }[] = [
  { value: 'main_entrance', label: 'Main entrance' },
  { value: 'service_entrance', label: 'Service entrance' },
  { value: 'loading_dock', label: 'Loading dock' },
  { value: 'mailroom', label: 'Mailroom' },
  { value: 'front_desk', label: 'Front desk' },
];
const TRI: { value: SurveyTri; label: string }[] = [
  { value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }, { value: 'unknown', label: "Didn't find out" },
];
const DAY: { value: SurveyDayHours['status']; label: string }[] = [
  { value: 'open', label: 'Open' }, { value: 'closed', label: 'Closed' }, { value: 'unknown', label: "Didn't find out" },
];
// Commercial first: 84% of the doors surveyed so far were commercial. Grouped
// under headings, which a native select cannot show on iOS (ADR-511 D4).
const TYPE_OPTIONS: SelectOption[] = (['commercial', 'residential'] as const).flatMap(cat => [
  { value: `h-${cat}`, label: cat === 'commercial' ? 'Commercial' : 'Residential', header: true },
  ...BUILDING_TYPES.filter(t => t.category === cat).map(t => ({ value: t.value, label: t.label })),
]);
// [D] The analysis: freight was each-unit 9 of 9; dock/mailroom one drop point 7 of 7.
const MODE_FOR_TYPE: Record<string, SurveyDeliveryMode | undefined> = {
  freight: 'each_unit', elevator: 'each_unit', walkup: 'each_unit',
  doorman_reception: 'each_unit', public_housing: 'each_unit',
  loading_dock: 'one_drop_point', loading_dock_mailroom: 'one_drop_point',
  mailroom: 'one_drop_point', lockers: 'one_drop_point',
};
const MAX_POINTS = 3;
// ADR-511 D1: grouped by when the answers are learned.
const STEPS = ['The building', 'Deliveries', 'Hours and note'] as const;
const OTHER_SIDE = '__other';

type Form = Required<Pick<SurveyObservationIn,
  'address_index' | 'source' | 'security_desk' | 'sign_in_required' | 'weekday' | 'saturday' | 'sunday'>>
  & { building_type: string; delivery_points: SurveyDeliveryPointIn[]; receives_for: number[];
      delivery_mode: SurveyDeliveryMode | null; floors: number | null; break_start: string; break_end: string;
      note: string };

const blank = (a: SurveyAddress): Form => ({
  address_index: a.index, source: 'observed', building_type: '',
  delivery_points: [{ point: 'main_entrance', side: a.sides?.[0] ?? null }],
  receives_for: [], security_desk: 'unknown', sign_in_required: 'unknown',
  delivery_mode: null, floors: null,
  weekday: { status: 'unknown' }, saturday: { status: 'unknown' }, sunday: { status: 'unknown' },
  break_start: '', break_end: '', note: '',
});

const DAY_LABEL = { weekday: 'Weekdays', saturday: 'Saturday', sunday: 'Sunday' } as const;

// ── drafts (ADR-511 D2) ───────────────────────────────────────────────────────
// Kept on this device until the door is saved. Storage can be missing or throw
// (a private window, blocked site data); then nothing is kept and the form still
// works, so every access is wrapped.

type Draft = { form: Form; step: number; showBreak: boolean };
const DRAFT_PREFIX = 'survey-draft:';
const draftKey = (walkId: string, index: number) => `${DRAFT_PREFIX}${walkId}:${index}`;

function readDraft(walkId: string, index: number): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(walkId, index));
    const d = raw ? JSON.parse(raw) as Draft : null;
    // A draft for another door, or from an older form shape, is not restored.
    return d?.form?.address_index === index && Array.isArray(d.form.delivery_points) ? d : null;
  } catch { return null; }
}
function writeDraft(walkId: string, index: number, d: Draft) {
  try { localStorage.setItem(draftKey(walkId, index), JSON.stringify(d)); } catch { /* not kept */ }
}
function dropDraft(walkId: string, index: number) {
  try { localStorage.removeItem(draftKey(walkId, index)); } catch { /* nothing to drop */ }
}
function draftDoors(walkId: string): Set<number> {
  const out = new Set<number>();
  try {
    const prefix = `${DRAFT_PREFIX}${walkId}:`;
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k?.startsWith(prefix)) out.add(Number(k.slice(prefix.length)));
    }
  } catch { /* none visible */ }
  return out;
}
function dropWalkDrafts(walkId: string) {
  for (const i of draftDoors(walkId)) dropDraft(walkId, i);
}

/** The first thing that would make the server refuse the hours, in words. */
function hoursProblem(f: Form, showBreak: boolean): string | null {
  for (const g of ['weekday', 'saturday', 'sunday'] as const) {
    const d = f[g];
    if (d.status === 'open' && (!d.open || !d.close)) {
      return `${DAY_LABEL[g]}: add both times, or choose "Didn't find out".`;
    }
  }
  if (showBreak && !f.break_start !== !f.break_end) return 'Weekday break: add both times, or remove it.';
  return null;
}

// ── controls ─────────────────────────────────────────────────────────────────

/** A radio group of chips. 44px tall (ADR-511 D3), arrow keys move the choice,
 *  and only the chosen chip is in the tab order, as for any radio group. */
function Chips<T extends string>({ value, options, onChange, label, allowClear = true }: {
  value: T | null | undefined; options: { value: T; label: string }[];
  onChange: (v: T | null) => void; label: string; allowClear?: boolean;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = options.findIndex(o => o.value === value);
  const onKey = (e: KeyboardEvent, i: number) => {
    const step = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1
      : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (i + step + options.length) % options.length;
    onChange(options[next].value);
    refs.current[next]?.focus();
  };
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o, i) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value}
          ref={el => { refs.current[i] = el; }}
          tabIndex={i === (current === -1 ? 0 : current) ? 0 : -1}
          onKeyDown={e => onKey(e, i)}
          onClick={() => onChange(value === o.value && allowClear ? null : o.value)}
          className={`min-h-11 rounded-full border px-4 text-sm ${value === o.value
            ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-muted'}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

const inputCls = 'min-h-11 rounded-lg border border-input bg-background px-3 py-2.5 text-sm';
const smallActionCls = 'btn-ghost min-h-11 px-3 text-sm';

function DayRow({ label, value, onChange, onSameAsWeekdays }: {
  label: string; value: SurveyDayHours; onChange: (v: SurveyDayHours) => void; onSameAsWeekdays?: () => void;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{label}</span>
        {onSameAsWeekdays && (
          <button type="button" onClick={onSameAsWeekdays} className={`${smallActionCls} -mr-2`}>Same as weekdays</button>
        )}
      </div>
      <Chips label={`${label} hours`} value={value.status} options={DAY} allowClear={false}
        onChange={s => onChange(s === 'open' ? { ...value, status: 'open' } : { status: s ?? 'unknown' })} />
      {value.status === 'open' && (
        <div className="flex items-center gap-2 text-sm">
          <input type="time" value={value.open ?? ''} aria-label={`${label} opens`} className={`${inputCls} min-w-0 flex-1`}
            onChange={e => onChange({ ...value, open: e.target.value })} />
          <span className="text-muted-foreground">to</span>
          <input type="time" value={value.close ?? ''} aria-label={`${label} closes`} className={`${inputCls} min-w-0 flex-1`}
            onChange={e => onChange({ ...value, close: e.target.value })} />
        </div>
      )}
    </div>
  );
}

function PointEditor({ index, value, sides, total, onChange, onRemove }: {
  index: number; value: SurveyDeliveryPointIn; sides: string[]; total: number;
  onChange: (v: SurveyDeliveryPointIn) => void; onRemove: () => void;
}) {
  const custom = value.side != null && value.side !== '' && !sides.includes(value.side);
  const sideOptions: SelectOption[] = [
    ...sides.map(sd => ({ value: sd, label: sd })),
    { value: OTHER_SIDE, label: 'Somewhere else…' },
  ];
  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Point {index + 1}</span>
        {total > 1 && (
          <button type="button" onClick={onRemove} aria-label={`Remove point ${index + 1}`}
            className="btn-ghost -mr-2 inline-flex h-11 w-11 items-center justify-center">
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <Chips label={`Point ${index + 1}`} value={value.point} options={POINTS} allowClear={false}
        onChange={v => onChange({ ...value, point: v ?? value.point })} />
      <span className="block text-xs text-muted-foreground">Which side</span>
      <SelectMenu touch ariaLabel={`Point ${index + 1}: which side`} placeholder="Choose a side"
        value={custom ? OTHER_SIDE : (value.side ?? '')} options={sideOptions}
        onChange={v => onChange({ ...value, side: v === OTHER_SIDE ? ' ' : v })} />
      {custom && (
        <input type="text" maxLength={120} value={value.side?.trim() ?? ''} className={`${inputCls} w-full`}
          onChange={e => onChange({ ...value, side: e.target.value })}
          placeholder="e.g. rear, via the alley" aria-label="Describe the side" />
      )}
      <div className="flex gap-2">
        <input type="number" inputMode="numeric" min={-5} max={200} value={value.floor ?? ''}
          onChange={e => onChange({ ...value, floor: e.target.value === '' ? null : Number(e.target.value) })}
          placeholder="Floor" aria-label="Floor" className={`${inputCls} w-24`} />
        {total > 1 && (
          <input type="text" maxLength={120} value={value.which_packages ?? ''}
            onChange={e => onChange({ ...value, which_packages: e.target.value })}
            placeholder="Which packages? e.g. for the ground-floor business"
            aria-label="Which packages go here" className={`${inputCls} min-w-0 flex-1`} />
        )}
      </div>
    </div>
  );
}

export default function SurveyWalkPage() {
  const { walkId } = useParams<{ walkId: string }>();
  const navigate = useNavigate();
  const reducedMotion = useReducedMotion();
  const [walk, setWalk] = useState<SurveyWalk | null>(null);
  const [door, setDoor] = useState<SurveyAddress | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [step, setStep] = useState(0);
  const [showBreak, setShowBreak] = useState(false);
  const [notPoint, setNotPoint] = useState<SurveyAddress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const stepHeading = useRef<HTMLHeadingElement>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await axiosClient.get<SurveyWalk>(`/survey/walks/${walkId}`);
      setWalk(data);
    } catch (e) {
      setError(errorText(e, "Couldn't load this walk."));
    }
  }, [walkId]);
  useEffect(() => { void load(); }, [load]);

  // D2: every change is kept, so an interruption costs nothing.
  // A door opened and left untouched is not a draft: "Draft" on the list must
  // mean there is something to come back to.
  useEffect(() => {
    if (!walk || !form || !door) return;
    const untouched = step === 0 && !showBreak && JSON.stringify(form) === JSON.stringify(blank(door));
    if (untouched) dropDraft(walk.id, form.address_index);
    else writeDraft(walk.id, form.address_index, { form, step, showBreak });
  }, [walk, door, form, step, showBreak]);

  // The "Saved" line goes after a few seconds; it is a confirmation, not a record.
  useEffect(() => {
    if (!saved) return;
    const t = window.setTimeout(() => setSaved(null), 4000);
    return () => window.clearTimeout(t);
  }, [saved]);

  const goTo = (n: number) => {
    setStep(n);
    window.scrollTo({ top: 0, behavior: reducedMotion ? 'auto' : 'smooth' });
    // Move focus to the step's heading so a screen reader announces the new step.
    window.requestAnimationFrame(() => stepHeading.current?.focus({ preventScroll: true }));
  };

  const open = (a: SurveyAddress) => {
    const d = walk ? readDraft(walk.id, a.index) : null;
    setDoor(a);
    setForm(d?.form ?? blank(a));
    setStep(d ? Math.min(Math.max(d.step, 0), STEPS.length - 1) : 0);
    setShowBreak(d?.showBreak ?? false);
    setError(null);
    setSaved(null);
    window.scrollTo({ top: 0 });
  };
  const close = () => { setDoor(null); setForm(null); };
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm(f => (f ? { ...f, [k]: v } : f));

  const setType = (t: string) => setForm(f => (f ? {
    ...f, building_type: t,
    // [D] Pre-fill only while the person hasn't chosen one themselves.
    delivery_mode: f.delivery_mode ?? MODE_FOR_TYPE[t] ?? null,
  } : f));

  const post = async (body: SurveyObservationIn, address: string) => {
    if (!walk) return;
    setBusy(true);
    setError(null);
    try {
      await axiosClient.post(`/survey/walks/${walk.id}/observations`, body);
      dropDraft(walk.id, body.address_index);
      close();
      setNotPoint(null);
      setSaved(`Saved ${address}`);
      await load();
    } catch (e) {
      setError(errorText(e, "Couldn't save this door."));
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    if (!form || !door) return;
    const problem = hoursProblem(form, showBreak);
    if (problem) { setError(problem); return; }
    const day = (d: SurveyDayHours): SurveyDayHours =>
      d.status === 'open' ? { status: 'open', open: d.open || null, close: d.close || null } : { status: d.status };
    void post({
      address_index: form.address_index, source: form.source, building_type: form.building_type,
      delivery_points: form.delivery_points.map(p => ({
        point: p.point, side: p.side?.trim() || null, floor: p.floor ?? null,
        which_packages: form.delivery_points.length > 1 ? (p.which_packages?.trim() || null) : null,
      })),
      receives_for: form.receives_for, security_desk: form.security_desk,
      sign_in_required: form.sign_in_required, delivery_mode: form.delivery_mode, floors: form.floors,
      weekday: day(form.weekday), saturday: day(form.saturday), sunday: day(form.sunday),
      break_start: showBreak ? (form.break_start || null) : null,
      break_end: showBreak ? (form.break_end || null) : null,
      note: form.note.trim() || null,
    }, door.address);
  };

  const finish = async () => {
    if (!walk) return;
    setBusy(true);
    try {
      await axiosClient.post(`/survey/walks/${walk.id}/close`);
      dropWalkDrafts(walk.id);
      navigate('/survey');
    } catch (e) {
      setError(errorText(e, "Couldn't finish the walk."));
      setBusy(false);
    }
  };

  if (!walk) {
    return <main className="mx-auto max-w-xl px-4 py-6"><ErrorBanner message={error} />
      {!error && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}</main>;
  }

  const done = new Set(walk.recorded);
  const closed = walk.closed_at !== null;

  if (door && form) {
    const sides = door.sides?.length ? door.sides : [door.address.split(' ').slice(1).join(' ')];
    const neighbours = door.neighbours ?? [];
    const last = step === STEPS.length - 1;
    const blocked = step === 0 && !form.building_type ? 'Choose a building type to go on.' : null;
    return (
      <main className="mx-auto max-w-xl px-4 py-6 space-y-5 pb-36">
        <button type="button" onClick={close} className={`${smallActionCls} -ml-3 inline-flex items-center gap-1`}>
          <ChevronLeft className="h-4 w-4" /> Doors
        </button>
        <header className="space-y-2">
          <h1 className="text-xl font-bold">{door.address}</h1>
          <div className="flex gap-1.5" aria-hidden="true">
            {STEPS.map((_, i) => (
              <span key={i} className={`h-1.5 flex-1 rounded-full ${i <= step ? 'bg-primary' : 'bg-muted'}`} />
            ))}
          </div>
          <h2 ref={stepHeading} tabIndex={-1} className="text-sm font-semibold text-muted-foreground outline-none">
            Step {step + 1} of {STEPS.length} · {STEPS[step]}
          </h2>
          <p className="text-xs text-muted-foreground">Your answers are kept on this phone until you save.</p>
        </header>
        <ErrorBanner message={error} />

        {step === 0 && (<>
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">Where did this come from?</h3>
            <Chips label="Source" value={form.source} options={SOURCES} allowClear={false}
              onChange={v => set('source', v ?? 'observed')} />
            <p className="text-xs text-muted-foreground">The role that answered, never the person's name.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">Building type</h3>
            <SelectMenu touch ariaLabel="Building type" placeholder="Choose…"
              value={form.building_type} options={TYPE_OPTIONS} onChange={setType} />
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">Each unit, or one drop point?</h3>
            <Chips<SurveyDeliveryMode> label="Delivery mode" value={form.delivery_mode}
              options={[{ value: 'each_unit', label: 'Each unit' }, { value: 'one_drop_point', label: 'One drop point' }]}
              onChange={v => set('delivery_mode', v)} />
            <input type="number" inputMode="numeric" min={1} max={200} value={form.floors ?? ''}
              onChange={e => set('floors', e.target.value ? Number(e.target.value) : null)}
              placeholder="Floors" aria-label="Number of floors" className={`${inputCls} w-32`} />
          </section>
        </>)}

        {step === 1 && (<>
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">Deliveries go to</h3>
            {form.delivery_points.map((p, i) => (
              <PointEditor key={i} index={i} value={p} sides={sides} total={form.delivery_points.length}
                onChange={v => set('delivery_points', form.delivery_points.map((x, j) => (j === i ? v : x)))}
                onRemove={() => set('delivery_points', form.delivery_points.filter((_, j) => j !== i))} />
            ))}
            {form.delivery_points.length < MAX_POINTS && (
              <button type="button" className={`${smallActionCls} inline-flex items-center gap-1`}
                onClick={() => set('delivery_points', [...form.delivery_points, { point: 'main_entrance', side: sides[0] }])}>
                <Plus className="h-4 w-4" /> Add another delivery point
              </button>
            )}
          </section>

          {neighbours.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-sm font-semibold">Also receives for</h3>
              <p className="text-xs text-muted-foreground">Other doors on this city block whose packages go here.</p>
              <div className="max-h-72 space-y-1 overflow-y-auto rounded-lg border border-border p-1">
                {neighbours.map((n, i) => (
                  <label key={n.address} className="flex min-h-11 items-center gap-3 rounded px-2 text-sm hover:bg-muted">
                    <input type="checkbox" className="h-5 w-5 shrink-0 accent-primary"
                      checked={form.receives_for.includes(i)}
                      onChange={e => set('receives_for', e.target.checked
                        ? [...form.receives_for, i] : form.receives_for.filter(x => x !== i))} />
                    {n.address}
                  </label>
                ))}
              </div>
            </section>
          )}

          <section className="space-y-3">
            <div className="space-y-1">
              <h3 className="text-sm font-semibold">Security desk</h3>
              <Chips label="Security desk" value={form.security_desk} options={TRI} allowClear={false}
                onChange={v => set('security_desk', v ?? 'unknown')} />
            </div>
            <div className="space-y-1">
              <h3 className="text-sm font-semibold">Sign-in required</h3>
              <Chips label="Sign-in required" value={form.sign_in_required} options={TRI} allowClear={false}
                onChange={v => set('sign_in_required', v ?? 'unknown')} />
            </div>
          </section>
        </>)}

        {step === 2 && (<>
          <section className="space-y-2">
            <h3 className="text-sm font-semibold">Receiving hours</h3>
            <DayRow label="Weekdays" value={form.weekday} onChange={v => set('weekday', v)} />
            <DayRow label="Saturday" value={form.saturday} onChange={v => set('saturday', v)}
              onSameAsWeekdays={() => set('saturday', { ...form.weekday })} />
            <DayRow label="Sunday" value={form.sunday} onChange={v => set('sunday', v)}
              onSameAsWeekdays={() => set('sunday', { ...form.weekday })} />
            {showBreak ? (
              <div className="space-y-2 rounded-lg border border-border p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">Weekday break</span>
                  <button type="button" className={`${smallActionCls} -mr-2`}
                    onClick={() => { setShowBreak(false); set('break_start', ''); set('break_end', ''); }}>
                    Remove
                  </button>
                </div>
                <div className="flex items-center gap-2 text-sm">
                  <input type="time" value={form.break_start} onChange={e => set('break_start', e.target.value)}
                    aria-label="Break starts" className={`${inputCls} min-w-0 flex-1`} />
                  <span className="text-muted-foreground">to</span>
                  <input type="time" value={form.break_end} onChange={e => set('break_end', e.target.value)}
                    aria-label="Break ends" className={`${inputCls} min-w-0 flex-1`} />
                </div>
              </div>
            ) : (
              <button type="button" onClick={() => setShowBreak(true)} className={`${smallActionCls} inline-flex items-center gap-1`}>
                <Plus className="h-4 w-4" /> Add a weekday break
              </button>
            )}
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-semibold">Note</h3>
            <textarea maxLength={500} rows={3} value={form.note} onChange={e => set('note', e.target.value)}
              aria-label="Note" className={`${inputCls} w-full`} />
            <p className="text-xs text-muted-foreground">
              Building facts only. No door or gate codes, no names, no security details.
            </p>
          </section>
        </>)}

        <div className="fixed inset-x-0 bottom-0 border-t border-border bg-background/95 px-4 py-3 backdrop-blur">
          <div className="mx-auto max-w-xl space-y-2">
            {blocked && <p className="text-center text-xs text-muted-foreground" role="status">{blocked}</p>}
            <div className="flex gap-2">
              {step > 0 && (
                <button type="button" onClick={() => goTo(step - 1)} disabled={busy}
                  className="btn-secondary min-h-11 px-4 text-sm inline-flex items-center gap-1">
                  <ChevronLeft className="h-4 w-4" /> Back
                </button>
              )}
              {last ? (
                <button type="button" onClick={save} disabled={busy}
                  className="btn-primary min-h-11 flex-1 text-sm inline-flex items-center justify-center gap-2">
                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Save this door
                </button>
              ) : (
                <button type="button" onClick={() => goTo(step + 1)} disabled={blocked !== null}
                  className="btn-primary min-h-11 flex-1 text-sm inline-flex items-center justify-center gap-1">
                  Next: {STEPS[step + 1]} <ChevronRight className="h-4 w-4" />
                </button>
              )}
            </div>
          </div>
        </div>
      </main>
    );
  }

  const drafts = draftDoors(walk.id);
  return (
    <main className="mx-auto max-w-xl px-4 py-6 space-y-4">
      <button type="button" onClick={() => navigate('/survey')}
        className={`${smallActionCls} -ml-3 inline-flex items-center gap-1`}>
        <ChevronLeft className="h-4 w-4" /> Survey
      </button>
      <header>
        <h1 className="text-xl font-bold">{walk.street}</h1>
        <p className="text-sm text-muted-foreground">
          {done.size} of {walk.addresses.length} doors recorded{closed ? ' · finished' : ''}
        </p>
      </header>
      <ErrorBanner message={error} />
      <p role="status" className={saved ? 'flex items-center gap-2 text-sm text-success' : 'sr-only'}>
        {saved && <><Check className="h-4 w-4" /> {saved}</>}
      </p>
      <ul className="space-y-2">
        {walk.addresses.map(a => (
          <li key={a.index} className="flex items-center gap-2">
            <button type="button" disabled={closed || done.has(a.index)} onClick={() => open(a)}
              className="flex min-h-11 min-w-0 flex-1 items-center justify-between gap-2 rounded-lg border border-border px-3 py-3 text-left text-sm hover:bg-muted disabled:opacity-60">
              <span className="truncate">{a.address}</span>
              {done.has(a.index) ? <Check className="h-4 w-4 shrink-0 text-success" aria-label="Recorded" />
                : drafts.has(a.index) && <span className="shrink-0 text-xs font-medium text-warning">Draft</span>}
            </button>
            {!closed && !done.has(a.index) && (
              <button type="button" onClick={() => setNotPoint(a)}
                className="btn-ghost min-h-11 shrink-0 px-2 text-xs" aria-label={`${a.address} is not a delivery point`}>
                Not a door
              </button>
            )}
          </li>
        ))}
      </ul>
      {!closed && (
        <button type="button" onClick={() => void finish()} disabled={busy} className="btn-secondary min-h-11 w-full text-sm">
          Finish walk
        </button>
      )}
      <ConfirmDialog
        open={notPoint !== null}
        title="Not a delivery point?"
        message={`${notPoint?.address ?? ''} will be recorded as not a delivery point (for example a gate or a second entrance).`}
        confirmLabel="Record it"
        onConfirm={() => notPoint && void post(
          { address_index: notPoint.index, source: 'observed', not_a_delivery_point: true }, notPoint.address)}
        onCancel={() => setNotPoint(null)}
      />
    </main>
  );
}
