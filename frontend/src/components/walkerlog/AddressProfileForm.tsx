import { useState } from 'react';
import { ChevronDown, ChevronRight, Trash2, AlertTriangle, Info } from 'lucide-react';
import Dropdown from './Dropdown';
import LabelScanner from './LabelScanner';
import {
  BUILDING_TYPES, TYPE_PROTOCOL, WORKLOAD_CLASSES, deriveWorkload, doorKey,
  type AddressProfile,
} from '../../utils/addressProfile';

/** One building's profile.
 *
 *  Three fields carry the weight — address, building type, workload class —
 *  and everything else is collapsed. That split is not cosmetic: the type and
 *  workload are what the sort algorithm and the walker UI actually consume,
 *  while hours and notes are enrichment. A form that asks for fifteen fields
 *  equally gets fifteen fields half-filled.
 *
 *  Workload DEFAULTS from the building type using the backend's own mapping,
 *  and stays overridable. The mapping is a default rather than a rule — a
 *  notoriously slow doorman is high_wait no matter what the door looks like,
 *  which is exactly why the production model keeps the two columns decoupled.
 */
const INPUT =
  'w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm ' +
  'focus:outline-none focus:ring-2 focus:ring-primary/40';

export default function AddressProfileForm({
  profile, onChange, onAddressCommitted, onDelete, known,
}: {
  profile: AddressProfile;
  /** Door keys already received by this campaign — see `alreadyKnown`. */
  known: Set<string>;
  onChange: (p: AddressProfile) => void;
  /** Fired on blur, once the address is settled — the caller re-keys there
   *  rather than on every keystroke, which would remount this form and steal
   *  focus after one character. */
  onAddressCommitted: (p: AddressProfile) => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(!profile.building_type);
  const set = (patch: Partial<AddressProfile>) => onChange({ ...profile, ...patch });

  /** Does this address match a door the campaign already received?
   *
   *  `known` is the set the page passes down — door keys the SERVER reported
   *  back as duplicates when this device last submitted. It is not a copy of
   *  the database and cannot be: there is no public read path (ADR-415 D4),
   *  so the set only grows by submitting an address and being told it was
   *  already there.
   *
   *  That makes the warning imperfect by construction — it cannot know about a
   *  door this device has never submitted. It catches the case that actually
   *  recurs: the same collector revisiting a building they were already told
   *  about, which without the warning happens again every single day. */
  const alreadyKnown =
    profile.address.trim().length > 3 && known.has(doorKey(profile.address));

  const typeLabel = BUILDING_TYPES.find((b) => b.value === profile.building_type)?.label;
  const workLabel = WORKLOAD_CLASSES.find((w) => w.value === profile.workload_class)?.label;

  return (
    /* NO overflow-hidden. It clipped every dropdown inside the form: a
       building-type list opened and was cut off mid-option by the card's
       edge, and Workload showed one row of four. `overflow` creates a
       clipping box that no z-index escapes, so the popup cannot simply be
       raised above it.

       It was only ever protecting the rounded corners of the collapsed
       header, and nothing here scrolls — the inner content is padded well
       inside the radius, so the corners stay clean without it. */
    <div className="card">
      <div className="flex items-center gap-2 p-3">
        <button type="button" onClick={() => setOpen((o) => !o)} className="shrink-0 rounded-md p-1 hover:bg-muted">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            {profile.address || <span className="text-muted-foreground">New address</span>}
          </p>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
            {typeLabel && <span className="whitespace-nowrap">{typeLabel}</span>}
            {workLabel && <span className="whitespace-nowrap">· {workLabel}</span>}
            {profile.troublesome && (
              <span className="whitespace-nowrap text-warning">· troublesome</span>
            )}
            {!profile.building_type && <span className="text-warning">needs a building type</span>}
          </div>
        </div>
        <button
          type="button" onClick={onDelete} title="Delete this profile"
          className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-danger/10 hover:text-danger"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      {open && (
        <div className="space-y-3 border-t border-border p-3">
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Address
            </label>
            <input
              value={profile.address}
              placeholder="e.g. 433 W 32 ST"
              onChange={(e) => set({ address: e.target.value })}
              onBlur={() => onAddressCommitted(profile)}
              className={`${INPUT} mt-1`}
            />
            {/* Scanning fills the address from a package label — the same
                reader the tote list uses. The TBA half is ignored here: a
                profile is about the building, not the parcel. */}
            <div className="mt-1.5">
              <LabelScanner
                compact
                label="Scan an address"
                onAccept={({ address }) => {
                  if (!address) return;
                  const next = { ...profile, address };
                  onChange(next);
                  // A scan settles the address in one action, so re-key now
                  // rather than waiting for a blur that may never come.
                  onAddressCommitted(next);
                }}
              />
            </div>
            {/* LOUD, INLINE, AND WHILE TYPING — not a banner after the fact.
                By the time a collector has filled in a building type and
                workload and pressed send, the wasted walk has already
                happened. This fires on the address itself, the moment the
                text matches a door the campaign already has. */}
            {alreadyKnown && (
              <p className="mt-1.5 flex items-start gap-1.5 rounded-lg border border-warning/50 bg-warning/10 px-2.5 py-2 text-xs font-medium text-warning">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>
                  Already collected. Someone has profiled this door for this
                  campaign, so you can skip it. Keep going if you are correcting
                  it.
                </span>
              </p>
            )}
            <p className="mt-1 text-[11px] text-muted-foreground">
              Type it as it appears. It is normalised later, not here.
            </p>
          </div>

          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Building type
            </label>
            <div className="mt-1">
              <Dropdown
                value={profile.building_type}
                placeholder="What is at the door?"
                ariaLabel="Building type"
                onChange={(v) => set({
                  building_type: v as AddressProfile['building_type'],
                  // Only fills an EMPTY workload — re-picking the type must not
                  // silently discard a deliberate override.
                  workload_class: profile.workload_class || deriveWorkload(v),
                })}
                options={BUILDING_TYPES.map((b) => ({ value: b.value, label: b.label }))}
              />
            </div>
            {profile.building_type && TYPE_PROTOCOL[profile.building_type] && (
              <p className="mt-1 flex items-start gap-1 text-[11px] text-muted-foreground">
                <Info className="mt-0.5 h-3 w-3 shrink-0" />
                {TYPE_PROTOCOL[profile.building_type]}
              </p>
            )}
          </div>

          <div>
            <div className="flex items-baseline justify-between gap-2">
              <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Workload
              </label>
              {profile.building_type
                && profile.workload_class !== deriveWorkload(profile.building_type) && (
                <button
                  type="button"
                  onClick={() => set({ workload_class: deriveWorkload(profile.building_type) })}
                  className="text-[11px] text-muted-foreground hover:text-foreground"
                >
                  overridden · reset
                </button>
              )}
            </div>
            <div className="mt-1">
              <Dropdown
                value={profile.workload_class}
                placeholder="How much work is it?"
                ariaLabel="Workload class"
                onChange={(v) => set({ workload_class: v })}
                options={WORKLOAD_CLASSES.map((w) => ({
                  value: w.value, label: w.label, description: w.hint,
                }))}
              />
            </div>
          </div>

          <details className="text-sm">
            <summary className="cursor-pointer text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              More detail (optional)
            </summary>

            <div className="mt-2 space-y-3">
              <div>
                <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Note
                </label>
                <textarea
                  rows={2} value={profile.note}
                  placeholder="Buzzer broken, use the side door…"
                  onChange={(e) => set({ note: e.target.value })}
                  className={`${INPUT} mt-1`}
                />
              </div>

              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Hours
                </p>
                <div className="mt-1 grid grid-cols-2 gap-2">
                  {([
                    ['opens_at', 'Opens'], ['closes_at', 'Closes'],
                    ['break_start', 'Break from'], ['break_end', 'Break to'],
                  ] as const).map(([k, label]) => (
                    <label key={k} className="min-w-0">
                      <span className="text-[11px] text-muted-foreground">{label}</span>
                      <input
                        type="time" value={profile[k]}
                        onChange={(e) => set({ [k]: e.target.value } as Partial<AddressProfile>)}
                        className={`${INPUT} mt-0.5`}
                      />
                    </label>
                  ))}
                </div>
              </div>

              <label className="flex items-start gap-2">
                <input
                  type="checkbox" checked={profile.troublesome}
                  onChange={(e) => set({ troublesome: e.target.checked })}
                  className="mt-0.5 shrink-0"
                />
                <span className="min-w-0 text-sm">
                  Troublesome
                  <span className="block text-[11px] text-muted-foreground">
                    Repeated failed deliveries, access problems, refusals.
                  </span>
                </span>
              </label>

              <div>
                <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Collected by
                </label>
                <input
                  value={profile.collected_by}
                  placeholder="Your name"
                  onChange={(e) => set({ collected_by: e.target.value })}
                  className={`${INPUT} mt-1`}
                />
              </div>
            </div>
          </details>

          {!profile.address.trim() && (
            <p className="flex items-start gap-1 text-[11px] text-warning">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              An address with no building type is a note, not a profile.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
