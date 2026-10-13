/**
 * One walk of one block (ADR-504): the city's doors, and a form per door.
 *
 * The field order comes from the address-free analysis of the old form
 * (2026-10-13 journal): receiving first (84% of doors were commercial), the
 * entrance as a structured choice (the old notes kept describing it), hours
 * prominent and breaks tucked away (58% vs 16% filled).
 */
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Check, ChevronLeft, Loader2 } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../../components/ui/ErrorBanner';
import { errorText } from '../../utils/errorText';
import { BUILDING_TYPES } from '../../utils/addressProfile';
import type {
  SurveyAddress, SurveyDeliveryMode, SurveyDeliveryPoint, SurveyObservationIn, SurveySource, SurveyWalk,
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
// Commercial first: 84% of the doors surveyed so far were commercial.
const TYPES = [...BUILDING_TYPES].sort((a, b) =>
  a.category === b.category ? 0 : a.category === 'commercial' ? -1 : 1);

type Tri = boolean | null;

const blank = (index: number): SurveyObservationIn => ({
  address_index: index, source: 'observed', building_type: '',
  delivery_point: null, entrance_side: '', security_desk: null, sign_in_required: null,
  delivery_mode: null, floors: null, opens_at: '', closes_at: '', break_start: '', break_end: '', note: '',
});

function Chips<T extends string>({ value, options, onChange, label }: {
  value: T | null | undefined; options: { value: T; label: string }[];
  onChange: (v: T | null) => void; label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
      {options.map(o => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value}
          onClick={() => onChange(value === o.value ? null : o.value)}
          className={`rounded-full border px-3 py-2 text-sm ${value === o.value
            ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-muted'}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function YesNo({ value, onChange, label }: { value: Tri; onChange: (v: Tri) => void; label: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm">{label}</span>
      <Chips<'yes' | 'no'> label={label}
        value={value === null ? null : value ? 'yes' : 'no'}
        options={[{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }]}
        onChange={v => onChange(v === null ? null : v === 'yes')} />
    </div>
  );
}

export default function SurveyWalkPage() {
  const { walkId } = useParams<{ walkId: string }>();
  const navigate = useNavigate();
  const [walk, setWalk] = useState<SurveyWalk | null>(null);
  const [door, setDoor] = useState<SurveyAddress | null>(null);
  const [form, setForm] = useState<SurveyObservationIn | null>(null);
  const [showBreak, setShowBreak] = useState(false);
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

  const open = (a: SurveyAddress) => {
    setDoor(a);
    setForm(blank(a.index));
    setShowBreak(false);
    setError(null);
  };
  const set = <K extends keyof SurveyObservationIn>(k: K, v: SurveyObservationIn[K]) =>
    setForm(f => (f ? { ...f, [k]: v } : f));

  const save = async () => {
    if (!form || !walk) return;
    setBusy(true);
    setError(null);
    // Empty strings mean "not answered": send null, never "".
    const clean = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v === '' ? null : v]));
    try {
      await axiosClient.post(`/survey/walks/${walk.id}/observations`, clean);
      setDoor(null);
      setForm(null);
      await load();
    } catch (e) {
      setError(errorText(e, "Couldn't save this door."));
    } finally {
      setBusy(false);
    }
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
    return (
      <main className="mx-auto max-w-xl px-4 py-6 space-y-5 pb-28">
        <button type="button" onClick={() => { setDoor(null); setForm(null); }}
          className="btn-ghost -ml-2 inline-flex items-center gap-1 text-sm">
          <ChevronLeft className="h-4 w-4" /> Doors
        </button>
        <h1 className="text-xl font-bold">{door.address}</h1>
        <ErrorBanner message={error} />

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Where did this come from?</h2>
          <Chips label="Source" value={form.source} options={SOURCES}
            onChange={v => set('source', v ?? 'observed')} />
          <p className="text-xs text-muted-foreground">The role that answered, never the person's name.</p>
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Deliveries go to</h2>
          <Chips label="Deliveries go to" value={form.delivery_point} options={POINTS}
            onChange={v => set('delivery_point', v)} />
          <input type="text" maxLength={120} value={form.entrance_side ?? ''}
            onChange={e => set('entrance_side', e.target.value)}
            placeholder="Which side? e.g. on 33rd St, rear via the alley"
            aria-label="Which side the entrance is on"
            className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm" />
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Building type</h2>
          <select value={form.building_type} onChange={e => set('building_type', e.target.value)}
            aria-label="Building type"
            className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm">
            <option value="">Choose…</option>
            {TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </section>

        <section className="space-y-3">
          <YesNo label="Security desk" value={form.security_desk ?? null} onChange={v => set('security_desk', v)} />
          <YesNo label="Sign-in required" value={form.sign_in_required ?? null} onChange={v => set('sign_in_required', v)} />
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Each unit, or one drop point?</h2>
          <Chips<SurveyDeliveryMode> label="Delivery mode" value={form.delivery_mode}
            options={[{ value: 'each_unit', label: 'Each unit' }, { value: 'one_drop_point', label: 'One drop point' }]}
            onChange={v => set('delivery_mode', v)} />
          <input type="number" inputMode="numeric" min={1} max={200} value={form.floors ?? ''}
            onChange={e => set('floors', e.target.value ? Number(e.target.value) : null)}
            placeholder="Floors" aria-label="Number of floors"
            className="w-32 rounded-lg border border-input bg-background px-3 py-2.5 text-sm" />
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Receiving hours</h2>
          <div className="flex items-center gap-2 text-sm">
            <input type="time" value={form.opens_at ?? ''} onChange={e => set('opens_at', e.target.value)}
              aria-label="Opens at" className="rounded-lg border border-input bg-background px-3 py-2" />
            <span className="text-muted-foreground">to</span>
            <input type="time" value={form.closes_at ?? ''} onChange={e => set('closes_at', e.target.value)}
              aria-label="Closes at" className="rounded-lg border border-input bg-background px-3 py-2" />
          </div>
          {showBreak ? (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">Break</span>
              <input type="time" value={form.break_start ?? ''} onChange={e => set('break_start', e.target.value)}
                aria-label="Break starts" className="rounded-lg border border-input bg-background px-3 py-2" />
              <span className="text-muted-foreground">to</span>
              <input type="time" value={form.break_end ?? ''} onChange={e => set('break_end', e.target.value)}
                aria-label="Break ends" className="rounded-lg border border-input bg-background px-3 py-2" />
            </div>
          ) : (
            <button type="button" onClick={() => setShowBreak(true)} className="btn-ghost text-xs">
              Add a break
            </button>
          )}
        </section>

        <section className="space-y-2">
          <h2 className="text-sm font-semibold">Note</h2>
          <textarea maxLength={500} rows={3} value={form.note ?? ''} onChange={e => set('note', e.target.value)}
            aria-label="Note"
            className="w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm" />
          <p className="text-xs text-muted-foreground">
            Building facts only. No door or gate codes, no names, no security details.
          </p>
        </section>

        <div className="fixed inset-x-0 bottom-0 border-t border-border bg-background/95 px-4 py-3">
          <div className="mx-auto max-w-xl">
            <button type="button" onClick={() => void save()} disabled={busy || !form.building_type}
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
          <li key={a.index}>
            <button type="button" disabled={closed || done.has(a.index)} onClick={() => open(a)}
              className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-3 text-left text-sm hover:bg-muted disabled:opacity-60">
              <span>{a.address}</span>
              {done.has(a.index) && <Check className="h-4 w-4 text-success" aria-label="Recorded" />}
            </button>
          </li>
        ))}
      </ul>
      {!closed && (
        <button type="button" onClick={() => void finish()} disabled={busy}
          className="btn-secondary w-full py-3 text-sm">
          Finish walk
        </button>
      )}
    </main>
  );
}
