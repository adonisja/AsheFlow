/**
 * The notification classifier (ADR-275 D1).
 *
 * This rule decides what earns space on a flooded screen, and one of its two
 * outcomes is operational: an unanswered `dispatch_assignment` can strand a
 * truck. It is also duplicated on web, so it is exactly the kind of logic that
 * needs pinning rather than eyeballing.
 *
 * The cases that matter are the boundaries — an unknown confirmation window, an
 * already-answered assignment, a missing dispatch_date — none of which are
 * visible in a screenshot of a working banner.
 */
import { isActionRequired, partitionNotifications } from '../classify';

const assignment = (over: Partial<{ id: string; dispatch_date: string | null }> = {}) => ({
  id: over.id ?? 'a1',
  type: 'dispatch_assignment',
  dispatch_date: over.dispatch_date === undefined ? '2026-08-16' : over.dispatch_date,
});

describe('isActionRequired', () => {
  it('flags an assignment whose window is pending', () => {
    expect(isActionRequired(assignment(), {
      confirmationStatus: { '2026-08-16': 'pending' },
    })).toBe(true);
  });

  it('treats an UNKNOWN window as open', () => {
    // The status fetch is async. Treating "not loaded yet" as closed would
    // collapse a live assignment for the first second after mount — exactly
    // when a walker is looking at it. Better a card that need not be there
    // than a missed confirmation.
    expect(isActionRequired(assignment(), {})).toBe(true);
  });

  it('does NOT flag one already confirmed or declined', () => {
    for (const status of ['confirmed', 'declined'] as const) {
      expect(isActionRequired(assignment(), {
        confirmationStatus: { '2026-08-16': status },
      })).toBe(false);
    }
  });

  it('does NOT flag one answered in this session', () => {
    // The optimistic local response, before the backend round-trip lands.
    expect(isActionRequired(assignment({ id: 'x' }), {
      answeredInSession: { x: 'confirmed' },
      confirmationStatus: { '2026-08-16': 'pending' },
    })).toBe(false);
  });

  it('does NOT flag one with no dispatch_date', () => {
    // Nothing to confirm against — it cannot be answered, so it is news.
    expect(isActionRequired(assignment({ dispatch_date: null }), {})).toBe(false);
  });

  it('never flags an informational type, whatever the window says', () => {
    const types = [
      'dispatch_assignment_info', 'dispatch_finalized', 'manifest_enrichment',
      'training_record_unsubmitted', 'zone_sort_complete',
      'dispatch_finalization_reminder', 'anchor_point_running_late',
    ];
    for (const type of types) {
      expect(isActionRequired(
        { id: 't', type, dispatch_date: '2026-08-16' },
        { confirmationStatus: { '2026-08-16': 'pending' } },
      )).toBe(false);
    }
  });
});

describe('partitionNotifications', () => {
  it('splits the real staging mix into 1 action + the rest', () => {
    // Proportions from the measured distribution: dispatch_assignment is 79%
    // of volume and the only actionable type.
    const list = [
      assignment({ id: 'a' }),
      { id: 'b', type: 'dispatch_finalized', dispatch_date: '2026-08-16' },
      { id: 'c', type: 'manifest_enrichment', dispatch_date: null },
      { id: 'd', type: 'training_record_unsubmitted', dispatch_date: null },
    ];
    const { action, info } = partitionNotifications(list, {
      confirmationStatus: { '2026-08-16': 'pending' },
    });
    expect(action.map(n => n.id)).toEqual(['a']);
    expect(info.map(n => n.id)).toEqual(['b', 'c', 'd']);
  });

  it('keeps TWO assignments both expanded', () => {
    // The case that rules out "show only one banner": a walker on two trucks
    // must answer both, and collapsing either can strand one.
    const list = [
      { id: 'a', type: 'dispatch_assignment', dispatch_date: '2026-08-16' },
      { id: 'b', type: 'dispatch_assignment', dispatch_date: '2026-08-17' },
    ];
    const { action, info } = partitionNotifications(list, {
      confirmationStatus: { '2026-08-16': 'pending', '2026-08-17': 'pending' },
    });
    expect(action).toHaveLength(2);
    expect(info).toHaveLength(0);
  });

  it('preserves order within each group', () => {
    const list = [
      { id: '1', type: 'manifest_enrichment', dispatch_date: null },
      { id: '2', type: 'dispatch_finalized', dispatch_date: null },
      { id: '3', type: 'zone_sort_complete', dispatch_date: null },
    ];
    const { info } = partitionNotifications(list, {});
    expect(info.map(n => n.id)).toEqual(['1', '2', '3']);
  });

  it('returns empty groups for an empty list', () => {
    const { action, info } = partitionNotifications([], {});
    expect(action).toEqual([]);
    expect(info).toEqual([]);
  });
});
