/**
 * The notification area's routing rules (ADR-516). Each case is a decision the
 * owner made: urgent is pinned, action items collapse to one row, ticker types
 * scroll, and only the right arrivals interrupt with a banner.
 */
import { arrivalOutcome, partitionArea } from '../area';

const n = (id: string, severity?: 'urgent' | 'action' | 'notice' | 'info', ticker = false) =>
  ({ id, severity, channels: ticker ? ['banner', 'ticker'] : ['banner'] });

describe('partitionArea', () => {
  it('pins urgent, rows action items, docks ticker types, leaves the rest to the inbox', () => {
    const p = partitionArea([n('u', 'urgent'), n('a', 'action'), n('t', 'info', true), n('me', 'info')]);
    expect(p.urgent.map(x => x.id)).toEqual(['u']);
    expect(p.needsYou.map(x => x.id)).toEqual(['a']);
    expect(p.ticker.map(x => x.id)).toEqual(['t']);
  });

  it('never shows an urgent notification in the ticker, even if it carries the ticker channel', () => {
    const p = partitionArea([n('u', 'urgent', true)]);
    expect(p.urgent).toHaveLength(1);
    expect(p.ticker).toHaveLength(0);
  });

  it('is empty when nothing is unread, so every part of the area hides (D1)', () => {
    expect(partitionArea([])).toEqual({ urgent: [], needsYou: [], ticker: [] });
  });

  it('treats a row from an older server (no severity) as inbox-only, not urgent', () => {
    const p = partitionArea([{ id: 'old' }]);
    expect(p.urgent.length + p.needsYou.length + p.ticker.length).toBe(0);
  });
});

describe('arrivalOutcome', () => {
  it('buzzes for urgent and banners the newest non-ticker arrival', () => {
    const o = arrivalOutcome([n('t', 'info', true), n('a', 'action'), n('u', 'urgent')]);
    expect(o.urgentHaptic).toBe(true);
    expect(o.banner?.id).toBe('a');
  });

  it('keeps the urgent haptic when a newer ticker event lands in the same refresh', () => {
    const o = arrivalOutcome([n('t', 'info', true), n('u', 'urgent')]);
    expect(o.urgentHaptic).toBe(true);
    expect(o.banner).toBeNull();
  });

  it('does nothing for ticker-only arrivals', () => {
    expect(arrivalOutcome([n('t', 'info', true)])).toEqual({ urgentHaptic: false, banner: null });
  });

  it('banners INFO about the reader (pto_approved-like)', () => {
    expect(arrivalOutcome([n('me', 'info')]).banner?.id).toBe('me');
  });
});
