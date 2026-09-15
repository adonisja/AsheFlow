import { useMemo, useState } from 'react';
import { Package, Trash2 } from 'lucide-react';
import Dropdown from './Dropdown';
import TotePicker from './TotePicker';
import { swatchFor } from './bagColors';
import LabelScanner from './LabelScanner';
import { bagToTote, type SeedBag } from '../../utils/walkerLogSeed';
import type { LogTote } from '../../utils/walkerLogDb';

/** A route's totes and the addresses each one carried.
 *
 *  Shared by BOTH route paths, which is the point of it existing. The claimed
 *  route (a walker's day) had this editor; the unclaimed builder rendered totes
 *  as bare chips with no address field at all — so on a build-first morning,
 *  which is the general case, there was nowhere to type the addresses you were
 *  handed with the truck. Addresses had to wait for someone to claim the route,
 *  which inverts the actual order of work.
 *
 *  Two copies of this markup would drift, so there is one.
 *
 *  Totes are CHOSEN, never typed: every option comes from the day's manifest,
 *  and the list a row offers is (still unassigned + the bag this row already
 *  holds). A bag on another route is absent from the list entirely, so a
 *  duplicate cannot be entered rather than being caught afterwards.
 */
const TEXT_INPUT =
  'w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm ' +
  'focus:outline-none focus:ring-2 focus:ring-primary/40';

/** The address textarea for one tote.
 *
 *  WHY THIS HOLDS ITS OWN DRAFT STRING. The stored value is `string[]`, so a
 *  naive controlled textarea has to `split('\n')` on every keystroke and
 *  `join('\n')` on every render. That round trip is lossy, and the loss lands
 *  exactly where the user is typing:
 *
 *    - `.trim()` on each line ate a space the moment it was typed, so "12 Main"
 *      could never be entered — the space vanished and the caret jumped back.
 *    - `.filter(Boolean)` dropped empty lines, so pressing Enter to start the
 *      next address immediately removed the new blank line.
 *
 *  So the textarea is uncontrolled WHILE FOCUSED: it keeps the raw text the
 *  user typed, spaces and blank lines intact, and only parses into `string[]`
 *  on blur. The parse still trims and drops blanks — that cleaning is right at
 *  the boundary, and wrong on every keystroke.
 *
 *  `draft === null` means "not being edited", so the box re-syncs when the
 *  addresses change from outside (a tote swap keeps its addresses, an import
 *  loads new ones) instead of showing a stale draft forever.
 */
function AddressBox({ addresses, onCommit }: {
  addresses: string[];
  onCommit: (addresses: string[]) => void;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const text = draft ?? addresses.join('\n');
  const lines = text.split('\n').filter((l) => l.trim());

  const commit = () => {
    if (draft === null) return;
    onCommit(draft.split('\n').map((s) => s.trim()).filter(Boolean));
    setDraft(null);
  };

  return (
    <>
      <textarea
        rows={Math.min(8, Math.max(2, lines.length + 1))}
        value={text}
        placeholder="One address per line"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        className={`${TEXT_INPUT} font-mono text-xs`}
      />
      <p className="text-[11px] text-muted-foreground">
        {lines.length} address{lines.length === 1 ? '' : 'es'}
        {draft !== null && <span className="ml-1 opacity-70">· unsaved, click away to keep</span>}
      </p>
    </>
  );
}

export default function ToteList({ totes, pool, onChange, dense }: {
  totes: LogTote[];
  /** Unclaimed bags. Excludes this route's own totes; they are added back below
   *  so each row's dropdown can render its current value. */
  pool: SeedBag[];
  onChange: (next: LogTote[]) => void;
  /** Slightly tighter chrome for the unclaimed builder, where routes stack. */
  dense?: boolean;
}) {
  const available = useMemo(() => {
    const mine = totes
      .filter((t) => t.stop !== undefined)
      .map((t) => ({
        bag_id: t.bag_id, sort_zone: t.sort_zone ?? '', stop: t.stop!,
        stop_package_count: t.stop_package_count ?? 0,
        stop_ov_count: t.stop_ov_count ?? 0,
        stop_bag_count: t.stop_bag_count ?? 1,
      }) as SeedBag);
    return [...pool, ...mine].sort((a, b) =>
      a.stop.localeCompare(b.stop, undefined, { numeric: true }) ||
      a.bag_id.localeCompare(b.bag_id));
  }, [pool, totes]);

  const byId = useMemo(() => new Map(available.map((b) => [b.bag_id, b])), [available]);

  const patch = (i: number, p: Partial<LogTote>) =>
    onChange(totes.map((t, x) => (x === i ? { ...t, ...p } : t)));

  /** Appends one scanned address to a tote.
   *
   *  Takes the index and re-reads the tote from `totes` at call time rather
   *  than closing over `t.addresses`. The scanner's onAccept fires minutes
   *  after it mounted — long enough for the user to have typed into the
   *  address box — and a captured array is the value from mount, so the append
   *  silently overwrote whatever had been typed since. Measured: an address
   *  typed by hand then a scan accepted left ONE address, not two. */
  const appendAddress = (i: number, address: string) => {
    const next = address.trim();
    if (!next) return;
    onChange(totes.map((t, x) => {
      if (x !== i) return t;
      if (t.addresses.includes(next)) return t;   // same box scanned twice
      return { ...t, addresses: [...t.addresses, next] };
    }));
  };

  const addressCount = totes.reduce((n, t) => n + t.addresses.length, 0);

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground inline-flex items-center gap-1.5">
          <Package className="w-3.5 h-3.5" /> Totes
          {totes.length > 0 && (
            <span className="normal-case tracking-normal text-muted-foreground">
              · {totes.length} bag{totes.length === 1 ? '' : 's'} · {addressCount} address{addressCount === 1 ? '' : 'es'}
            </span>
          )}
        </h4>
        {/* ADDS from the raw pool, NOT from `available` — that list re-includes
            this route's own totes, and offering it here would let the same bag
            be added twice. */}
        <TotePicker
          pool={pool}
          onPick={(b) => {
            if (totes.some((t) => t.bag_id === b.bag_id)) return;
            onChange([...totes, bagToTote(b)]);
          }}
        />
      </div>

      {totes.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No totes yet. Add the bags this route carried, then type their addresses.
        </p>
      )}

      {totes.map((t, ti) => (
        <div key={t.bag_id || ti} className={`rounded-lg border border-border space-y-2 ${dense ? 'p-2.5' : 'p-3'}`}>
          <div className="flex gap-2 items-center">
            {/* Swapping a row keeps its addresses: the correction is WHICH bag
                was carried, not what was in it. */}
            <Dropdown
              className="flex-1 min-w-0"
              value={t.bag_id}
              placeholder="Pick a tote"
              ariaLabel="Tote"
              onChange={(v) => {
                const b = byId.get(v);
                if (b) patch(ti, { ...bagToTote(b), addresses: t.addresses });
              }}
              options={[
                // A bag off a previous manifest, or hand-entered before this
                // list existed, is not in `available` — keep it as an option so
                // opening an old day does not silently blank it.
                ...(!byId.has(t.bag_id) && t.bag_id
                  ? [{ value: t.bag_id, label: t.bag_id, hint: 'not on today’s manifest' }]
                  : []),
                ...available.map((b) => ({
                  value: b.bag_id,
                  label: b.bag_id,
                  hint: b.sort_zone,
                  description: b.stop,
                  swatch: swatchFor(b.bag_id),
                })),
              ]}
            />
            {t.stop && (
              <span className="text-[11px] text-muted-foreground whitespace-nowrap shrink-0">
                {t.stop} · {t.sort_zone}
              </span>
            )}
            <button
              onClick={() => onChange(totes.filter((_, i) => i !== ti))}
              className="p-2 rounded-md text-muted-foreground hover:text-danger hover:bg-danger/10 shrink-0"
              type="button" title="Remove tote"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>

          {/* One address per line: pasting a block from a sheet or notes is the
              common case, and a repeated add-row is slower. */}
          <AddressBox
            addresses={t.addresses}
            onCommit={(addresses) => patch(ti, { addresses })}
          />

          {/* Scanning APPENDS rather than replaces: a tote holds many packages,
              so each label read adds one more address to the bag's list. A
              duplicate is dropped — scanning the same box twice is a slip, not
              two stops.

              Labelled and full-width, unlike the compact scanner on an RTS or
              OV row. Those sit beside a single field; this one sits under a
              textarea holding a growing list, where an unlabelled icon button
              reads as decoration rather than "add another address". */}
          <div className="flex items-center gap-2">
            <LabelScanner
              compact
              label="Scan an address"
              onAccept={({ address }) => { if (address) appendAddress(ti, address); }}
            />
            <span className="text-[11px] text-muted-foreground">
              adds one more line
            </span>
          </div>
        </div>
      ))}
    </section>
  );
}
