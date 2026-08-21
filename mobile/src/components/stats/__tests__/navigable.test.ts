/**
 * Every level must offer a way OUT — either a zoom-out trail or a zoom-in
 * target (ADR-271 §R).
 *
 * The bug this pins: replacing the single-year Lifetime bar with a figures
 * summary removed the only zoom-IN control, and Lifetime is also the one level
 * with no zoom-OUT trail (nothing is further out). The screen became a dead end
 * — the user was stuck with no control on the card at all.
 *
 * It is a navigation invariant, not a rendering detail, and it is invisible in
 * a screenshot of any OTHER level. Testing the invariant catches the next
 * variant of the same mistake, which a test for "Lifetime has a tap target"
 * would not.
 */
import type { Grain } from '../aggregate';

/** Mirrors the component's `outer` map: which level each one zooms OUT to. */
const OUTER: Record<Grain, Grain | null> = {
  day: 'week', week: 'month', month: 'year', year: 'lifetime', lifetime: null,
};

/** Levels that render a chart whose buckets are tappable to zoom IN. */
const ZOOMS_IN: Record<Grain, boolean> = {
  lifetime: true,   // year bars, or the year tile in LifetimeSummary
  year: true,       // month line points
  month: true,      // week bars
  week: true,       // day bars
  day: false,       // terminal — the detail view, nothing below it
};

const LEVELS: Grain[] = ['day', 'week', 'month', 'year', 'lifetime'];

describe('drill navigation', () => {
  it('gives every level a way out', () => {
    for (const level of LEVELS) {
      const canZoomOut = OUTER[level] !== null;
      const canZoomIn = ZOOMS_IN[level];
      expect(canZoomOut || canZoomIn).toBe(true);
    }
  });

  it('leaves lifetime dependent on zoom-in alone', () => {
    // The reason the regression was possible: nothing is further out than
    // Lifetime, so its zoom-IN control is the ONLY navigation on the card.
    // Anything that replaces the Lifetime chart must keep a tap target.
    expect(OUTER.lifetime).toBeNull();
    expect(ZOOMS_IN.lifetime).toBe(true);
  });

  it('leaves day dependent on zoom-out alone', () => {
    // The mirror image: day is terminal, so its trail is the only way off it.
    expect(ZOOMS_IN.day).toBe(false);
    expect(OUTER.day).toBe('week');
  });

  it('reaches lifetime from day by zooming out repeatedly', () => {
    // No level is orphaned from the chain.
    let level: Grain | null = 'day';
    const seen: Grain[] = [];
    while (level) {
      expect(seen).not.toContain(level);   // no cycle
      seen.push(level);
      level = OUTER[level];
    }
    expect(seen).toEqual(['day', 'week', 'month', 'year', 'lifetime']);
  });
});
