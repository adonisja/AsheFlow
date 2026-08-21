/**
 * Crew slot ordering (ADR-271 §P, ADR-256).
 *
 * The operator asked whether the provision for CAPTAINS is there, given no
 * captain exists in the data today: "the captains render exactly under drivers
 * … so that section won't get rendered on null data, but the provision should
 * be there".
 *
 * That is exactly the kind of rule that cannot be verified by looking at the
 * screen — the current data can never exercise it. It has to be a test, or it
 * is an assumption that silently rots until the first captain is hired.
 */
import { groupCrew } from '../crew';

const roles = (crew: { name: string; role: string }[]) =>
  groupCrew(crew).map(([role]) => role);

describe('groupCrew', () => {
  it('places captain directly under driver regardless of wire order', () => {
    // The API does not promise an order, so the UI must impose one.
    expect(roles([
      { name: 'W1', role: 'walker' },
      { name: 'T1', role: 'trainee' },
      { name: 'C1', role: 'captain' },
      { name: 'D1', role: 'driver' },
      { name: 'TR1', role: 'trainer' },
    ])).toEqual(['driver', 'captain', 'trainer', 'walker', 'trainee']);
  });

  it('omits the captain group entirely when no captain worked', () => {
    // Today's reality. An empty group would render a header and a gap, which
    // reads as a loading failure rather than as "nobody held that slot".
    const out = roles([
      { name: 'W1', role: 'walker' },
      { name: 'D1', role: 'driver' },
      { name: 'T1', role: 'trainee' },
    ]);
    expect(out).toEqual(['driver', 'walker', 'trainee']);
    expect(out).not.toContain('captain');
  });

  it('keeps multiple captains in one group, still in slot two', () => {
    const out = groupCrew([
      { name: 'W1', role: 'walker' },
      { name: 'C1', role: 'captain' },
      { name: 'D1', role: 'driver' },
      { name: 'C2', role: 'captain' },
    ]);
    expect(out.map(([r]) => r)).toEqual(['driver', 'captain', 'walker']);
    expect(out[1][1]).toEqual(['C1', 'C2']);
  });

  it('lets captain lead when the truck has no driver', () => {
    // A captain can run a truck alone (ADR-256): the ordering must not assume
    // a driver row exists above them.
    expect(roles([
      { name: 'W1', role: 'walker' },
      { name: 'C1', role: 'captain' },
    ])).toEqual(['captain', 'walker']);
  });

  it('keeps an unknown role and sorts it ABOVE the known ones', () => {
    // `indexOf` returns -1 for an unrecognised role, so it sorts to the front.
    // Pinned deliberately rather than left as an accident of the sort: a role
    // this build has never heard of is more likely a new senior slot than a
    // new carrier, and burying it at the bottom would hide it. The important
    // half is that it is never DROPPED — a crew member who does not render is
    // worse than one in the wrong place.
    const out = roles([
      { name: 'D1', role: 'driver' },
      { name: 'X1', role: 'dispatch' },
    ]);
    expect(out).toContain('dispatch');
    expect(out).toEqual(['dispatch', 'driver']);
  });
});
