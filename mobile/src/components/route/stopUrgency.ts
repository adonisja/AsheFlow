// Per-stop cutoff-urgency gradient (ADR-216 Phase 3).
//
// The server sends FACTS (cutoff_state + minutes_to_cutoff) and the two window
// sizes; the COLOUR is derived here, client-side, because it is now-relative and
// continuous — a server-computed hex would be stale seconds after it was sent.
//
// Continuum, safe → critical (intensity monotonic; hue flips at the boundaries):
//   no cutoff        → BLUE   (flat)
//   > (N+M) away     → GREEN  deepest far out, DESATURATING toward the caution edge
//   caution (N..N+M) → YELLOW light at the far edge, INTENSIFYING toward urgent
//   urgent (<= N)    → RED    full on entry, DEEPENING toward now
//   past break       → distinct on-break tone (reopens shown as text)
//   past closing     → distinct closed tone ("call customer")
//
// N = urgent window, M = caution window (minutes; both server-configurable).

import { ramp } from '@theme/generated-colors';

export type CutoffState = 'none' | 'future' | 'on_break' | 'closed';

export type StopUrgency = {
  state: CutoffState;
  /** left-accent-bar colour */
  color: string;
  /** band label for intra-list ordering: 0 closed, 1 on_break, 2 red, 3 yellow, 4 green, 5 blue */
  rank: number;
};

// ── tiny hex-lerp (no deps) ─────────────────────────────────────────────────
function hexToRgb(h: string): [number, number, number] {
  const s = h.replace('#', '');
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
}
function rgbToHex(r: number, g: number, b: number): string {
  const c = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, '0');
  return `#${c(r)}${c(g)}${c(b)}`;
}
/** t in [0,1]: 0 → a, 1 → b */
function mix(a: string, b: string, t: number): string {
  const u = Math.max(0, Math.min(1, t));
  const [ar, ag, ab] = hexToRgb(a);
  const [br, bg, bb] = hexToRgb(b);
  return rgbToHex(ar + (br - ar) * u, ag + (bg - ag) * u, ab + (bb - ab) * u);
}

// Anchors from the GENERATED ramp (design/palette.json -> `ramp`).
// These were the last consumers of the legacy hardcoded `palette` export, which
// was a second competing source of truth alongside the generated tokens.
// "deep" = saturated/dark end, "pale" = light end.
const BLUE        = ramp.urgencyNone;         // no cutoff
const GREEN_DEEP  = ramp.urgencyFarDeep;      // far-future: confident deep green
const GREEN_PALE  = ramp.urgencyFarPale;      // green draining toward the caution edge
const YELLOW_PALE = ramp.urgencyCautionPale;  // caution: light at the far edge
const YELLOW_DEEP = ramp.urgencyCautionDeep;  // caution intensifying toward urgent
const RED_ON      = ramp.urgencyUrgent;       // urgent: full on entry
const RED_DEEP    = ramp.urgencyClosed;       // urgent deepening toward now
const CLOSED      = ramp.urgencyClosed;       // past closing
const ON_BREAK    = ramp.urgencyCautionDeep;  // on break — distinct, not-red

// How far out (in multiples of the green band width) we treat as "fully deep
// green". Beyond FLAT_MULT * greenWidth, the green stops getting deeper.
const FLAT_MULT = 3;

/**
 * Resolve the accent colour + ordering rank for one stop.
 *
 * @param state    server cutoff_state
 * @param minutes  server minutes_to_cutoff (>0 future, <=0 overdue; may be null)
 * @param urgentN  urgent window minutes (red)
 * @param cautionM caution window minutes (yellow), immediately before the urgent window
 */
export function resolveStopUrgency(
  state: CutoffState,
  minutes: number | null | undefined,
  urgentN: number,
  cautionM: number,
): StopUrgency {
  if (state === 'closed')   return { state, color: CLOSED,   rank: 0 };
  if (state === 'on_break') return { state, color: ON_BREAK, rank: 1 };
  if (state === 'none' || minutes == null) return { state: 'none', color: BLUE, rank: 5 };

  // future — position within the bands by minutes-to-cutoff.
  const N = Math.max(1, urgentN);
  const M = Math.max(1, cautionM);

  if (minutes <= N) {
    // RED: full on entering (minutes == N) → deepening toward now (minutes → 0).
    const t = 1 - minutes / N;               // 0 at the edge, 1 at now
    return { state, color: mix(RED_ON, RED_DEEP, t), rank: 2 };
  }
  if (minutes <= N + M) {
    // YELLOW: light at the far edge (minutes == N+M) → intensifying toward N.
    const t = (N + M - minutes) / M;         // 0 at far edge, 1 at the urgent edge
    return { state, color: mix(YELLOW_PALE, YELLOW_DEEP, t), rank: 3 };
  }
  // GREEN: deepest far out → DESATURATING (paler) as it approaches the caution edge.
  const green = minutes - (N + M);           // minutes beyond the caution window
  const span = FLAT_MULT * (N + M);          // how far out counts as "fully deep"
  const t = Math.min(1, green / span);       // 0 at the caution edge, 1 far out
  // t=1 far out → deep; t=0 near caution → pale, so mix pale→deep by t.
  return { state, color: mix(GREEN_PALE, GREEN_DEEP, t), rank: 4 };
}

/** Chip text for the row's time indicator. */
export function cutoffChipText(
  state: CutoffState,
  cutoffAt: string | null | undefined,
  reopensAt: string | null | undefined,
): string | null {
  switch (state) {
    case 'closed':   return cutoffAt ? `Closed ${cutoffAt} · call customer` : 'Closed · call customer';
    case 'on_break': return reopensAt ? `On break · reopens ${reopensAt}` : 'On break';
    case 'future':   return cutoffAt ? `Closes ${cutoffAt}` : null;
    default:         return null;
  }
}
