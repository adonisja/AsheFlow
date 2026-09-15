/** Physical bag colours, shared by every control that shows a tote.
 *
 *  Lives here rather than inside TotePicker because the tote row's dropdown
 *  shows the same swatch: two copies of this map would drift the first time a
 *  new colour appears in a workbook, and the two controls would disagree about
 *  what a "Green" bag looks like.
 *
 *  Unknown colours fall through to a neutral swatch rather than disappearing —
 *  a new colour next week must not render an invisible row. */
const BAG_COLORS: Record<string, string> = {
  navy: '#1e3a8a',
  black: '#27272a',
  green: '#15803d',
  yellow: '#eab308',
  orange: '#ea580c',
  red: '#dc2626',
  blue: '#2563eb',
  purple: '#7e22ce',
  white: '#e5e7eb',
  grey: '#6b7280',
  gray: '#6b7280',
};

export const swatchFor = (bagId: string): string =>
  BAG_COLORS[bagId.trim().split(/\s+/)[0]?.toLowerCase() ?? ''] ?? '#94a3b8';
