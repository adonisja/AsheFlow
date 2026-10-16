import { formatRelative } from '../time';

const NOW = Date.parse('2026-10-15T12:00:00Z');
const ago = (ms: number) => new Date(NOW - ms).toISOString();

describe('formatRelative', () => {
  it.each([
    [30_000, 'Just now'],
    [60_000, '1m ago'],
    [59 * 60_000, '59m ago'],
    [60 * 60_000, '1h ago'],
    [23 * 3_600_000, '23h ago'],
    [24 * 3_600_000, 'Yesterday'],
    [3 * 86_400_000, '3d ago'],
  ])('%i ms ago reads %s', (ms, text) => {
    expect(formatRelative(ago(ms), NOW)).toBe(text);
  });

  it('returns nothing for an unreadable timestamp rather than "NaNm ago"', () => {
    expect(formatRelative('not a date', NOW)).toBe('');
  });
});
