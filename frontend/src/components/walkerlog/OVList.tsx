import { Boxes, Plus, Trash2 } from 'lucide-react';
import Dropdown from './Dropdown';
import LabelScanner from './LabelScanner';
import { OV_SIZES, emptyOV, type LogOV, type OVSize } from '../../utils/walkerLogDb';

/** Oversized packages on a route.
 *
 *  An OV is ONE package too large to ride inside a tote, so it is recorded as
 *  its own unit rather than an extra line in a tote's address box — the call
 *  the production model already makes (ADR-400 A4). Putting it in a tote would
 *  overstate that tote's contents and throw away the size, which is the only
 *  field that says what the thing costs the walker to carry.
 *
 *  Unlike a bag there is nothing to pick from: the BTR sheet gives a COUNT and
 *  a sort zone per stop, never identities. So every field here is typed, and
 *  every field may be blank — an OV with an address and no id is still a real
 *  delivery, and the count alone is worth recording when the walker is moving.
 *
 *  The manifest's own OV count for the route's stops is shown beside the
 *  header, so "sheet said 5, I logged 3" is visible while entering rather than
 *  only after export.
 */
const TEXT_INPUT =
  'w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm ' +
  'focus:outline-none focus:ring-2 focus:ring-primary/40';

export default function OVList({ ovs, expected, onChange }: {
  ovs: LogOV[];
  /** OVs the manifest predicted for this route's stops, or null when the route
   *  has no manifest totes to predict from. */
  expected: number | null;
  onChange: (next: LogOV[]) => void;
}) {
  const patch = (i: number, p: Partial<LogOV>) =>
    onChange(ovs.map((o, x) => (x === i ? { ...o, ...p } : o)));

  const addressed = ovs.filter((o) => o.address.trim()).length;

  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground inline-flex items-center gap-1.5">
          <Boxes className="w-3.5 h-3.5" /> OVs
          {ovs.length > 0 && (
            <span className="normal-case tracking-normal text-muted-foreground">
              · {ovs.length} logged · {addressed} addressed
            </span>
          )}
          {expected !== null && expected > 0 && (
            <span
              className={`normal-case tracking-normal ${
                ovs.length === expected ? 'text-muted-foreground' : 'text-warning'
              }`}
            >
              · sheet says {expected}
            </span>
          )}
        </h4>
        <button
          type="button"
          onClick={() => onChange([...ovs, emptyOV()])}
          className="btn-secondary text-xs px-2.5 py-1 inline-flex items-center gap-1.5"
        >
          <Plus className="w-3.5 h-3.5" /> Add OV
        </button>
      </div>

      {ovs.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {expected !== null && expected > 0
            ? `No OVs logged. The sheet expects ${expected} on this route's stops.`
            : 'No oversized packages on this route.'}
        </p>
      )}

      {ovs.map((o, i) => (
        <div key={i} className="rounded-lg border border-border p-3 space-y-2">
          <div className="flex gap-2 items-center">
            <span className="text-[11px] font-semibold text-muted-foreground shrink-0 w-8">
              #{i + 1}
            </span>
            <input
              value={o.ov_id}
              placeholder="OV id (e.g. OV1042), optional"
              onChange={(e) => patch(i, { ov_id: e.target.value })}
              className={`${TEXT_INPUT} font-mono text-xs`}
            />
            <button
              type="button"
              onClick={() => onChange(ovs.filter((_, x) => x !== i))}
              title="Remove this OV"
              className="p-2 rounded-md text-muted-foreground hover:text-danger hover:bg-danger/10 shrink-0"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Size
              </label>
              <div className="mt-1">
                <Dropdown
                  value={o.size}
                  placeholder="Pick a size"
                  ariaLabel="OV size"
                  onChange={(v) => patch(i, { size: v as OVSize })}
                  options={OV_SIZES.map((sz) => ({
                    value: sz,
                    label: sz,
                    // XS and S actually fit in a tote; M and up ride on the
                    // cart. That is the distinction the size is recording.
                    description: sz === 'XS' || sz === 'S' ? 'fits in a tote' : 'rides on the cart',
                  }))}
                />
              </div>
            </div>
            <div>
              <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Sort zone
              </label>
              <input
                value={o.sort_zone}
                placeholder="e.g. B-16.1T"
                onChange={(e) => patch(i, { sort_zone: e.target.value })}
                className={`${TEXT_INPUT} mt-1 font-mono text-xs`}
              />
            </div>
          </div>

          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Address
            </label>
            {/* One address: an OV is one package going to one place. */}
            <input
              value={o.address}
              placeholder="Where this OV was delivered"
              onChange={(e) => patch(i, { address: e.target.value })}
              className={`${TEXT_INPUT} mt-1`}
            />
            {/* An OV is ONE package, so a scan REPLACES both fields rather than
                appending the way a tote's address list does. */}
            <div className="mt-1.5">
              <LabelScanner
                compact
                onAccept={({ tba, address }) => patch(i, {
                  ...(address ? { address } : {}),
                  ...(tba && !o.ov_id ? { ov_id: tba } : {}),
                })}
              />
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}
