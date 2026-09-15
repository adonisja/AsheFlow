import { X } from 'lucide-react';
import { DIFFICULTIES } from '../../utils/walkerLogDb';

/** The walker's difficulty rating — a segmented scale, not a dropdown.
 *
 *  Difficulty is FOUR ORDERED VALUES, and that ordering is the whole point: the
 *  rating gets compared against route minutes and package load, so what matters
 *  when entering it is where this route sits relative to the others. A dropdown
 *  hides the scale behind a click and shows one value at a time, which is the
 *  worst possible presentation for an ordinal judgement — you cannot see that
 *  "moderate" has "hard" and "brutal" above it without opening the menu.
 *
 *  Laid out flat, the scale is visible, one tap sets it, and the colour ramp
 *  (green through red) makes a filled-in day scannable at a glance.
 *
 *  Unrated stays reachable: "not rated" is a real state — the walker never gave
 *  a rating — and must be distinguishable from "easy", so clearing is an
 *  explicit × rather than a fifth step on the scale.
 */

/** The scale's colour comes entirely from the token layer.
 *
 *  `dot` was a hex literal rendered through an inline style, which is the exact
 *  shape the contrast gate cannot see: a literal does not follow a palette
 *  change and never reaches the checker. The severity here is semantic
 *  (easy/moderate/hard/brutal maps onto success/warning/danger), so there was
 *  no reason for it to be a literal — the sibling `on` classes were already
 *  tokens. Escalation within warning is carried by opacity, not by a second
 *  hand-picked yellow. */
const SCALE: Record<string, { label: string; dot: string; on: string }> = {
  easy:     { label: 'Easy',     dot: 'bg-success',      on: 'bg-success/15 border-success/50 text-success' },
  moderate: { label: 'Moderate', dot: 'bg-warning/70',   on: 'bg-warning/15 border-warning/50 text-warning' },
  hard:     { label: 'Hard',     dot: 'bg-warning',      on: 'bg-warning/20 border-warning/60 text-warning' },
  brutal:   { label: 'Brutal',   dot: 'bg-danger',       on: 'bg-danger/15 border-danger/50 text-danger' },
};

export default function DifficultyPicker({ value, onChange }: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Difficulty <span className="normal-case tracking-normal">(walker's rating)</span>
        </label>
        {value && (
          <button
            type="button" onClick={() => onChange('')}
            className="text-[11px] text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5"
            title="Clear the rating"
          >
            <X className="w-3 h-3" /> clear
          </button>
        )}
      </div>

      <div role="radiogroup" aria-label="Difficulty" className="flex gap-1">
        {DIFFICULTIES.map((d) => {
          const spec = SCALE[d];
          const on = value === d;
          return (
            <button
              key={d}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => onChange(on ? '' : d)}
              title={spec.label}
              className={`flex-1 min-w-0 rounded-lg border px-1 py-1.5 text-xs font-medium transition-colors ${
                on ? spec.on : 'border-border text-muted-foreground hover:bg-muted'
              }`}
            >
              <span
                aria-hidden
                className={`inline-block w-1.5 h-1.5 rounded-full mr-1 align-middle ${spec.dot} ${on ? '' : 'opacity-30'}`}
              />
              <span className="align-middle truncate">{spec.label}</span>
            </button>
          );
        })}
      </div>

      {!value && (
        <p className="text-[11px] text-muted-foreground mt-1">Not rated.</p>
      )}
    </div>
  );
}
