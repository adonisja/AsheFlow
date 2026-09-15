import { useState } from 'react';
import { Check } from 'lucide-react';
import {
  BUILDING_CATEGORIES, BUILDING_TYPES, type AddressProfile,
} from '../../utils/addressProfile';

/** Picking a building type, as a two-step drill-down.
 *
 *  WHY NOT THE SHARED <Dropdown>. It rendered all ten types in one scrolling
 *  popup with category headings. On a phone that put every Commercial option
 *  below the fold: the grouping was decoration, and finding "Freight" meant
 *  scrolling a menu that was itself inside a scrolling page. A collector at a
 *  door is doing this one-handed.
 *
 *  Two steps instead. Residential or Commercial is a distinction anyone makes
 *  before they reach the door, and answering it first cuts ten options to at
 *  most five — which fit on screen with no scrolling at all.
 *
 *  INLINE, NOT A POPUP. There is no overlay, so there is nothing to clip, no
 *  drop-up calculation, and no way to lose the list behind a card edge — the
 *  exact bug this replaces. It costs vertical space, which the form has, and
 *  buys a target that cannot be mispositioned.
 *
 *  The stored value is still the LEAF. The category is presentation only: the
 *  server derives the real one from the type (ADR-418 D1), so this component
 *  never sends it.
 */
export default function BuildingTypePicker({ value, onChange }: {
  value: AddressProfile['building_type'];
  onChange: (v: AddressProfile['building_type']) => void;
}) {
  const selected = BUILDING_TYPES.find((b) => b.value === value);

  /** A category chosen but not yet resolved to a type.
   *
   *  The DISPLAYED category prefers the selected type's own category, so
   *  re-opening a saved profile lands on the right step without anyone
   *  touching it — holding this in state alone would start on the wrong
   *  category until the first tap. `pending` only matters between choosing a
   *  category and choosing a type under it. */
  const [pending, setPending] = useState<string | null>(null);
  /** Is the leaf list open? Open until something is chosen, then collapsed to
   *  a summary row. Reopened by tapping "change". */
  const [expanded, setExpanded] = useState(false);
  const category = selected?.category ?? pending;

  const types = BUILDING_TYPES.filter((b) => b.category === category);

  return (
    <div className="space-y-1.5">
      {/* STEP 1 — two buttons, always visible. Keeping them on screen after a
          choice makes switching category one tap rather than a back-out. */}
      <div className="grid grid-cols-2 gap-1.5">
        {BUILDING_CATEGORIES.map((c) => {
          const on = category === c.value;
          return (
            <button
              key={c.value}
              type="button"
              aria-pressed={on}
              onClick={() => {
                // Switching category clears the type: a residential leaf is not
                // valid under Commercial, and silently keeping it would leave
                // the form showing one thing and holding another.
                if (category !== c.value) onChange('');
                setPending(c.value);
                // A new category always shows its options: there is nothing
                // chosen under it yet, so a collapsed summary would be blank.
                setExpanded(true);
              }}
              className={`rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors ${
                on
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border hover:border-primary/60 hover:bg-muted'
              }`}
            >
              {c.label}
            </button>
          );
        })}
      </div>

      {/* STEP 2 — appears only once a category is chosen, and COLLAPSES to a
          single row once one is picked.
          
          Measured on a 390px viewport: five leaf buttons pushed the chosen one
          below the fold, so the answer to "what did I pick" required scrolling
          past the options. Collapsing keeps the whole form visible and makes
          the selection the thing you see, with one tap to change it. */}
      {category && selected && !expanded && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="flex w-full items-start gap-2 rounded-lg border border-primary bg-primary/10 px-3 py-2.5 text-left text-sm font-medium text-primary"
        >
          <Check className="mt-0.5 h-4 w-4 shrink-0" />
          {/* WRAPS, never truncates. "Loading dock / service entrance" lost its
              last word to an ellipsis, which is the half that distinguishes it
              from "Loading dock: mailroom" — a truncated label here is worse
              than a taller row, because the row exists to tell you what you
              picked. */}
          <span className="min-w-0 flex-1">{selected.label}</span>
          <span className="mt-0.5 shrink-0 text-[11px] font-normal opacity-70">change</span>
        </button>
      )}

      {category && (!selected || expanded) && (
        <div className="space-y-1">
          {types.map((b) => {
            const on = b.value === value;
            return (
              <button
                key={b.value}
                type="button"
                aria-pressed={on}
                onClick={() => { onChange(b.value); setExpanded(false); }}
                className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors ${
                  on
                    ? 'border-primary bg-primary/10 font-medium text-primary'
                    : 'border-border hover:border-primary/60 hover:bg-muted'
                }`}
              >
                {/* The tick occupies its slot whether or not it is shown, so
                    selecting one does not shift every label sideways. */}
                <Check className={`h-4 w-4 shrink-0 ${on ? '' : 'invisible'}`} />
                <span className="min-w-0">{b.label}</span>
              </button>
            );
          })}
        </div>
      )}

      {!category && (
        <p className="text-[11px] text-muted-foreground">
          Residential or commercial first, then what is at the door.
        </p>
      )}
    </div>
  );
}
