import { useState } from 'react';
import { ChevronDown, ChevronRight, Trash2, AlertTriangle, Info } from 'lucide-react';
import BuildingTypePicker from './BuildingTypePicker';
import LabelScanner from './LabelScanner';
import type { CheckResult } from '../../utils/collectionSubmit';
import {
  BUILDING_TYPES, OTHER, SECURITY_DESK_PROTOCOL,
  TYPE_PROTOCOL, WORKLOAD_TAGS, addressShapeError, doorKey, isIncompatible,
  workloadError,
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
  profile, onChange, onAddressCommitted, onDelete, known, verdict, checking,
}: {
  profile: AddressProfile;
  /** Door keys already received by this campaign — see `alreadyKnown`. */
  known: Set<string>;
  /** What the campaign said about this address, or null when it has not been
   *  settled yet. Gates the rest of the form (ADR-420): a collector enters the
   *  door, clicks away, and the classification fields open once the campaign
   *  has answered — so nobody fills in a profile for a door that turns out to
   *  be closed. */
  verdict: CheckResult | null;
  /** The server check is in flight for this profile. */
  checking: boolean;
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
  /** Has the address been settled? An unlocked verdict (or `unknown`, meaning
   *  offline or no campaign link) opens the rest of the form. A locked door
   *  never gets here — the row is cleared on blur. */
  const settled = verdict !== null && !(verdict.state === 'known' && verdict.locked);

  const alreadyKnown =
    profile.address.trim().length > 3 && known.has(doorKey(profile.address));

  const typeLabel = BUILDING_TYPES.find((b) => b.value === profile.building_type)?.label;
  /** Workloads for the collapsed header. Joined rather than truncated to one:
   *  the whole point of the multi-select is that a door can be two things, and
   *  a summary showing only the first would hide exactly that. */
  const workLabel = profile.workloads
    .map((t) => (t === OTHER
      // The collapsed header shows what "other" MEANT, not the word "other",
      // which would tell the reader nothing they could act on.
      ? (profile.workload_other.trim() || 'other')
      : WORKLOAD_TAGS.find((w) => w.value === t)?.label ?? t))
    .join(', ');

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
              // ADR-436. Enter commits, because an address is ONE LINE and
              // nothing here wants a newline. Clicking outside was the only way
              // to leave the field, which is an invisible requirement: the
              // collector types an address, presses Enter, nothing happens, and
              // the duplicate check they are waiting for never runs.
              //
              // blur() rather than calling onAddressCommitted directly — that
              // fires the existing onBlur, so there is ONE commit path instead
              // of two that must be kept in step. It also moves focus out, which
              // is what the collector asked for by pressing Enter.
              //
              // preventDefault stops an enclosing form from submitting.
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  e.currentTarget.blur();
                }
              }}
              enterKeyHint="done"
              className={`${INPUT} mt-1`}
            />
            {/* ADR-449 D4. Shown as the collector types, once they have typed
                enough to mean something — flagging an empty field is noise. The
                server is what actually rejects; this exists so the collector is
                not told at submit time, by which point they may be at the next
                building. */}
            {profile.address.trim().length > 2 &&
              addressShapeError(profile.address) && (
                <p className="mt-1 text-[11px] text-warning">
                  {addressShapeError(profile.address)}
                </p>
              )}
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
            {checking && (
              <p className="mt-1.5 text-[11px] text-muted-foreground">
                Checking whether this door is already collected…
              </p>
            )}

            {/* THE AUTHORITATIVE REJECTION. The server was asked about this
                exact door across the whole campaign, so this catches a
                COWORKER's entry — the case the local hint below cannot see and
                the one that actually wastes a walk.

                Loud on purpose: a duplicate discovered here saves a trip, and
                one missed costs somebody a walk to a door that was done. */}
            {verdict?.state === 'known' ? (
              <div className="mt-1.5 rounded-lg border border-warning/50 bg-warning/10 px-2.5 py-2">
                {/* An invitation, not a rejection: a second look either
                    confirms the first or disagrees, and both are informative.

                    Says WHAT, never HOW MANY. "Yours will be the second and
                    last" told a token holder the exact threshold that closes a
                    door — the procedure rather than the outcome. A door at the
                    limit never reaches this form anyway; the row is cleared on
                    blur. */}
                <p className="flex items-start gap-1.5 text-xs font-semibold text-warning">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>
                    {/* ADR-426. "You recorded this" and "someone recorded this"
                        are different facts and want different actions: the
                        first invites a correction, the second invites a second
                        opinion. */}
                    {verdict.mine
                      ? 'You recorded this door'
                      : 'Already recorded'}
                    {verdict.collected_on ? `, on ${verdict.collected_on}` : ''}.
                    {verdict.mine
                      ? ' Submitting again updates your entry.'
                      : ' Another look is still useful.'}
                  </span>
                </p>
                <p className="mt-1 pl-5 text-[11px] text-warning/80">
                  {verdict.mine
                    ? 'Change what you need to and submit.'
                    : 'Fill it in as you find it. If it disagrees with what is there, that disagreement is the useful part.'}
                </p>
              </div>
            ) : alreadyKnown && (
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

          {/* ── Everything below is gated on the address being settled ──────
              ADR-420. The collector enters the door, clicks away, the campaign
              is asked, and only then does the classification open.

              Why gate rather than let people fill it in and reject on submit:
              a door at the verification limit is closed, and discovering that
              AFTER typing a building type, a workload and hours is the wasted
              work this whole check exists to prevent. `unknown` (offline, or
              no campaign link) opens the form too — a collector logging
              locally must never be blocked by a check they cannot make. */}
          {!settled ? (
            <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-[11px] text-muted-foreground">
              {checking
                ? 'Checking the address…'
                : 'Enter the address, then press Enter or tap outside to continue.'}
            </p>
          ) : (
          <>

          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Building type
            </label>
            <div className="mt-1">
              <BuildingTypePicker
                value={profile.building_type}
                onChange={(v) => set({ building_type: v })}
              />
            </div>

            {/* A FLAG, not a type. The old taxonomy had `biz_security` as its
                own building type, which forced a false choice: a loading dock
                WITH a security desk had to be filed as one or the other. A
                security desk is an attribute of the door, so it sits beside
                the type rather than competing with it. */}
            <label className="mt-2 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={profile.has_security_desk}
                onChange={(e) => set({ has_security_desk: e.target.checked })}
                className="h-4 w-4 rounded border-border accent-primary"
              />
              <span>
                Security desk
                <span className="ml-1 text-[11px] font-normal text-muted-foreground">
                  (requires photo ID)
                </span>
              </span>
            </label>

            {profile.building_type && TYPE_PROTOCOL[profile.building_type] && (
              <p className="mt-1 flex items-start gap-1 text-[11px] text-muted-foreground">
                <Info className="mt-0.5 h-3 w-3 shrink-0" />
                {TYPE_PROTOCOL[profile.building_type]}
                {profile.has_security_desk && ` ${SECURITY_DESK_PROTOCOL}`}
              </p>
            )}
          </div>

          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Workload <span className="normal-case tracking-normal">(all that apply)</span>
            </label>

            {/* CHECKBOXES, not a dropdown, and no prefill from building type.
                The old version derived one value from the type and let it be
                overridden — a guess dressed as data, right often enough to be
                believed. A doorman building that is also 20+ floors is
                genuinely both bulk drop and high-rise, which one value could
                not say. */}
            <div className="mt-1 space-y-1">
              {WORKLOAD_TAGS.map((w) => {
                // A walk-up is neither a high-rise nor a bulk drop. DISABLED
                // rather than hidden: a box that vanishes when you pick a type
                // looks like a rendering glitch, where a greyed one with a
                // reason teaches the rule. The server rejects the pair too —
                // this is the explanation, not the guarantee.
                const blocked = isIncompatible(profile.building_type, w.value);
                return (
                  <label
                    key={w.value}
                    title={blocked ? `Not possible for a ${typeLabel?.toLowerCase()}.` : undefined}
                    className={`flex items-start gap-2 text-sm ${blocked ? 'opacity-40' : ''}`}
                  >
                    <input
                      type="checkbox"
                      disabled={blocked}
                      checked={profile.workloads.includes(w.value)}
                      onChange={(e) => set({
                        workloads: e.target.checked
                          // Ticking a real tag clears "other": the four tags
                          // not fitting and one of them fitting cannot both be
                          // true, and making the user untick it first is
                          // friction with no purpose.
                          ? [...profile.workloads.filter((t) => t !== OTHER), w.value]
                          : profile.workloads.filter((t) => t !== w.value),
                        ...(e.target.checked ? { workload_other: '' } : {}),
                      })}
                      className="mt-0.5 h-4 w-4 shrink-0 rounded border-border accent-primary disabled:cursor-not-allowed"
                    />
                    <span className="min-w-0">
                      {w.label}
                      <span className="block text-[11px] text-muted-foreground">{w.hint}</span>
                    </span>
                  </label>
                );
              })}

              {/* Separated by a rule: an answer ABOUT the others, not a peer
                  of them. Ticking it clears the rest and opens a text field —
                  "the four do not fit" is only useful alongside what does. */}
              <label className="mt-1 flex items-start gap-2 border-t border-border pt-1.5 text-sm">
                <input
                  type="checkbox"
                  checked={profile.workloads.includes(OTHER)}
                  onChange={(e) => set({
                    workloads: e.target.checked ? [OTHER] : [],
                    // Clearing the tag clears the text: orphaned text is a
                    // value nothing would ever read, and the server rejects it.
                    ...(e.target.checked ? {} : { workload_other: '' }),
                  })}
                  className="mt-0.5 h-4 w-4 shrink-0 rounded border-border accent-primary"
                />
                <span className="min-w-0">
                  Other
                  <span className="block text-[11px] text-muted-foreground">
                    none of the four fit
                  </span>
                </span>
              </label>

              {profile.workloads.includes(OTHER) && (
                <input
                  autoFocus
                  value={profile.workload_other}
                  onChange={(e) => set({ workload_other: e.target.value })}
                  maxLength={200}
                  placeholder="What makes this door different?"
                  className={`${INPUT} mt-1`}
                />
              )}
            </div>

            {/* Shown once the address exists, so a brand-new empty row does not
                open already scolding the collector. */}
            {profile.address.trim()
              && workloadError(profile.workloads, profile.building_type, profile.workload_other) && (
              <p className="mt-1 flex items-start gap-1 text-[11px] font-medium text-warning">
                <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                {workloadError(profile.workloads, profile.building_type, profile.workload_other)}
              </p>
            )}
          </div>

          {/* ADR-436 D2. WAS 11px uppercase muted text with the browser's
              default triangle, and collectors were not finding it — so the note,
              the hours and the troublesome flag, which are what make a profile
              worth more than a building type, went uncollected. A disclosure
              affordance needs contrast and a clear label; that had neither.

              Still <details>/<summary>: the element IS a disclosure, keyboard-
              operable and screen-reader-announced without re-implementing any of
              it. `list-none` and the webkit marker rule drop the default triangle
              so the chevron is the only marker, rotating on expand. */}
          <details className="group text-sm">
            <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg border border-border bg-surface/40 px-3 py-2 transition-colors hover:border-primary/60 hover:bg-muted [&::-webkit-details-marker]:hidden">
              <ChevronDown
                aria-hidden="true"
                className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
              />
              <span className="font-medium">More detail</span>
              {/* Names what is inside. "optional" alone tells the collector they
                  may skip it and nothing about what they would be skipping. */}
              <span className="text-[11px] text-muted-foreground">note, hours, access</span>
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

            </div>
          </details>

          </>
          )}
        </div>
      )}
    </div>
  );
}
