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
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Check, ChevronLeft, Loader2, Plus, X } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../../components/ui/ErrorBanner';
import ConfirmDialog from '../../components/ui/ConfirmDialog';
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
// Commercial first: 84% of the doors surveyed so far were commercial.
const TYPES = [...BUILDING_TYPES].sort((a, b) =>
  a.category === b.category ? 0 : a.category === 'commercial' ? -1 : 1);
// [D] The analysis: freight was each-unit 9 of 9; dock/mailroom one drop point 7 of 7.
const MODE_FOR_TYPE: Record<string, SurveyDeliveryMode | undefined> = {
  freight: 'each_unit', elevator: 'each_unit', walkup: 'each_unit',
  doorman_reception: 'each_unit', public_housing: 'each_unit',
  loading_dock: 'one_drop_point', loading_dock_mailroom: 'one_drop_point',
  mailroom: 'one_drop_point', lockers: 'one_drop_point',
};
const MAX_POINTS = 3;

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

function Chips<T extends string>({ value, options, onChange, label, allowClear = true }: {
  value: T | null | undefined; options: { value: T; label: string }[];
  onChange: (v: T | null) => void; label: string; allowClear?: boolean;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
      {options.map(o => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value}
          onClick={() => onChange(value === o.value && allowClear ? null : o.value)}
          className={`rounded-full border px-3 py-2 text-sm ${value === o.value
            ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-muted'}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

const inputCls = 'rounded-lg border border-input bg-background px-3 py-2.5 text-sm';

function DayRow({ label, value, onChange, onSameAsWeekdays }: {
  label: string; value: SurveyDayHours; onChange: (v: SurveyDayHours) => void; onSameAsWeekdays?: () => void;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium">{label}</span>
        {onSameAsWeekdays && (
          <button type="button" onClick={onSameAsWeekdays} className="btn-ghost text-xs">Same as weekdays</button>
        )}
      </div>
      <Chips label={`${label} hours`} value={value.status} options={DAY} allowClear={false}
        onChange={s => onChange(s === 'open' ? { ...value, status: 'open' } : { status: s ?? 'unknown' })} />
      {value.status === 'open' && (
        <div className="flex items-center gap-2 text-sm">
          <input type="time" value={value.open ?? ''} aria-label={`${label} opens`} className={inputCls}
            onChange={e => onChange({ ...value, open: e.target.value })} />
          <span className="text-muted-foreground">to</span>
          <input type="time" value={value.close ?? ''} aria-label={`${label} closes`} className={inputCls}
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
  return (
    <div className="space-y-2 rounded-lg border border-border p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Point {index + 1}</span>
        {total > 1 && (
          <button type="button" onClick={onRemove} className="btn-ghost p-1" aria-label={`Remove point ${index + 1}`}>
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <Chips label={`Point ${index + 1}`} value={value.point} options={POINTS} allowClear={false}
        onChange={v => onChange({ ...value, point: v ?? value.point })} />
      <label className="block text-xs text-muted-foreground" htmlFor={`side-${index}`}>Which side</label>
      <select id={`side-${index}`} className={`${inputCls} w-full`}
        value={custom ? '__other' : (value.side ?? '')}
        onChange={e => onChange({ ...value, side: e.target.value === '__other' ? ' ' : e.target.value })}>
        {sides.map(sd => <option key={sd} value={sd}>{sd}</option>)}
        <option value="__other">Somewhere else…</option>
      </select>
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
  const [walk, setWalk] = useState<SurveyWalk | null>(null);
  const [door, setDoor] = useState<SurveyAddress | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [showBreak, setShowBreak] = useState(false);
  const [notPoint, setNotPoint] = useState<SurveyAddress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await axiosClient.get<SurveyWalk>(`/survey/walks/${walkId}`);
      setWalk(data);
    } catch (e) {
      setError(errorText(e, "Couldn't load this walk."));
    }
  }, [walkId]);
  useEffect(() => { void load(); }, [load]);

  const open = (a: SurveyAddress) => { setDoor(a); setForm(blank(a)); setShowBreak(false); setError(null); };
  const close = () => { setDoor(null); setForm(null); };
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm(f => (f ? { ...f, [k]: v } : f));

  const setType = (t: string) => setForm(f => (f ? {
    ...f, building_type: t,
    // [D] Pre-fill only while the person hasn't chosen one themselves.
    delivery_mode: f.delivery_mode ?? MODE_FOR_TYPE[t] ?? null,
  } : f));

  const post = async (body: SurveyObservationIn) => {
    if (!walk) return;
    setBusy(true);
    setError(null);
    try {
      await axiosClient.post(`/survey/walks/${walk.id}/observations`, body);
      close();
      setNotPoint(null);
      await load();
    } catch (e) {
      setError(errorText(e, "Couldn't save this door."));
    } finally {
      setBusy(false);
    }
  };

  const save = () => {
    if (!form) return;
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
      break_start: form.break_start || null, break_end: form.break_end || null,
      note: form.note.trim() || null,
    });
  };

  const finish = async () => {
    if (!walk) return;
    setBusy(true);
    try {
      await axiosClient.post(`/survey/walks/${walk.id}/close`);
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
    return (
      <main className="mx-auto max-w-xl px-4 py-6 space-y-5 pb-28">
        <button type="button" onClick={close} className="btn-ghost -ml-2 inline-flex items-center gap-1 text-sm">
          <ChevronLeft className="h-4 w-4" /> Doors
        </button>
        <h1 className="text-xl font-bold">{door.address}</h1>
        <ErrorBanner message={error} />

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Where did this come from?</h2>
          <Chips label="Source" value={form.source} options={SOURCES} allowClear={false}
            onChange={v => set('source', v ?? 'observed')} />
          <p className="text-xs text-muted-foreground">The role that answered, never the person's name.</p>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Building type</h2>
          <select value={form.building_type} onChange={e => setType(e.target.value)} aria-label="Building type"
            className={`${inputCls} w-full`}>
            <option value="">Choose…</option>
            {TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Deliveries go to</h2>
          {form.delivery_points.map((p, i) => (
            <PointEditor key={i} index={i} value={p} sides={sides} total={form.delivery_points.length}
              onChange={v => set('delivery_points', form.delivery_points.map((x, j) => (j === i ? v : x)))}
              onRemove={() => set('delivery_points', form.delivery_points.filter((_, j) => j !== i))} />
          ))}
          {form.delivery_points.length < MAX_POINTS && (
            <button type="button" className="btn-ghost inline-flex items-center gap-1 text-sm"
              onClick={() => set('delivery_points', [...form.delivery_points, { point: 'main_entrance', side: sides[0] }])}>
              <Plus className="h-4 w-4" /> Add another delivery point
            </button>
          )}
        </section>

        {neighbours.length > 0 && (
          <section className="space-y-2">
            <h2 className="text-sm font-semibold">Also receives for</h2>
            <p className="text-xs text-muted-foreground">Other doors on this city block whose packages go here.</p>
            <div className="max-h-56 space-y-1 overflow-y-auto rounded-lg border border-border p-2">
              {neighbours.map((n, i) => (
                <label key={n.address} className="flex items-center gap-3 rounded px-2 py-2 text-sm hover:bg-muted">
                  <input type="checkbox" className="h-4 w-4 accent-primary"
                    checked={form.receives_for.includes(i)}
                    onChange={e => set('receives_for', e.target.checked
                      ? [...form.receives_for, i] : form.receives_for.filter(x => x !== i))} />
                  {n.address}
                </label>
              ))}
            </div>
          </section>
        )}

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Each unit, or one drop point?</h2>
          <Chips<SurveyDeliveryMode> label="Delivery mode" value={form.delivery_mode}
            options={[{ value: 'each_unit', label: 'Each unit' }, { value: 'one_drop_point', label: 'One drop point' }]}
            onChange={v => set('delivery_mode', v)} />
          <input type="number" inputMode="numeric" min={1} max={200} value={form.floors ?? ''}
            onChange={e => set('floors', e.target.value ? Number(e.target.value) : null)}
            placeholder="Floors" aria-label="Number of floors" className={`${inputCls} w-32`} />
        </section>

        <section className="space-y-3">
          <div className="space-y-1">
            <span className="text-sm font-semibold">Security desk</span>
            <Chips label="Security desk" value={form.security_desk} options={TRI} allowClear={false}
              onChange={v => set('security_desk', v ?? 'unknown')} />
          </div>
          <div className="space-y-1">
            <span className="text-sm font-semibold">Sign-in required</span>
            <Chips label="Sign-in required" value={form.sign_in_required} options={TRI} allowClear={false}
              onChange={v => set('sign_in_required', v ?? 'unknown')} />
          </div>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Receiving hours</h2>
          <DayRow label="Weekdays" value={form.weekday} onChange={v => set('weekday', v)} />
          <DayRow label="Saturday" value={form.saturday} onChange={v => set('saturday', v)}
            onSameAsWeekdays={() => set('saturday', { ...form.weekday })} />
          <DayRow label="Sunday" value={form.sunday} onChange={v => set('sunday', v)}
            onSameAsWeekdays={() => set('sunday', { ...form.weekday })} />
          {showBreak ? (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Weekday break</span>
              <input type="time" value={form.break_start} onChange={e => set('break_start', e.target.value)}
                aria-label="Break starts" className={inputCls} />
              <span className="text-muted-foreground">to</span>
              <input type="time" value={form.break_end} onChange={e => set('break_end', e.target.value)}
                aria-label="Break ends" className={inputCls} />
            </div>
          ) : (
            <button type="button" onClick={() => setShowBreak(true)} className="btn-ghost text-xs">Add a break</button>
          )}
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Note</h2>
          <textarea maxLength={500} rows={3} value={form.note} onChange={e => set('note', e.target.value)}
            aria-label="Note" className={`${inputCls} w-full`} />
          <p className="text-xs text-muted-foreground">
            Building facts only. No door or gate codes, no names, no security details.
          </p>
        </section>

        <div className="fixed inset-x-0 bottom-0 border-t border-border bg-background/95 px-4 py-3">
          <div className="mx-auto max-w-xl">
            <button type="button" onClick={save} disabled={busy || !form.building_type}
              className="btn-primary w-full py-3 text-sm inline-flex items-center justify-center gap-2">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              Save this door
            </button>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-xl px-4 py-6 space-y-4">
      <button type="button" onClick={() => navigate('/survey')}
        className="btn-ghost -ml-2 inline-flex items-center gap-1 text-sm">
        <ChevronLeft className="h-4 w-4" /> Survey
      </button>
      <header>
        <h1 className="text-xl font-bold">{walk.street}</h1>
        <p className="text-sm text-muted-foreground">
          {done.size} of {walk.addresses.length} doors recorded{closed ? ' · finished' : ''}
        </p>
      </header>
      <ErrorBanner message={error} />
      <ul className="space-y-2">
        {walk.addresses.map(a => (
          <li key={a.index} className="flex items-center gap-2">
            <button type="button" disabled={closed || done.has(a.index)} onClick={() => open(a)}
              className="flex min-w-0 flex-1 items-center justify-between rounded-lg border border-border px-3 py-3 text-left text-sm hover:bg-muted disabled:opacity-60">
              <span className="truncate">{a.address}</span>
              {done.has(a.index) && <Check className="h-4 w-4 shrink-0 text-success" aria-label="Recorded" />}
            </button>
            {!closed && !done.has(a.index) && (
              <button type="button" onClick={() => setNotPoint(a)}
                className="btn-ghost shrink-0 px-2 py-3 text-xs" title="This address isn't a delivery point">
                Not a door
              </button>
            )}
          </li>
        ))}
      </ul>
      {!closed && (
        <button type="button" onClick={() => void finish()} disabled={busy} className="btn-secondary w-full py-3 text-sm">
          Finish walk
        </button>
      )}
      <ConfirmDialog
        open={notPoint !== null}
        title="Not a delivery point?"
        message={`${notPoint?.address ?? ''} will be recorded as not a delivery point (for example a gate or a second entrance).`}
        confirmLabel="Record it"
        onConfirm={() => notPoint && void post({ address_index: notPoint.index, source: 'observed', not_a_delivery_point: true })}
        onCancel={() => setNotPoint(null)}
      />
    </main>
  );
}
