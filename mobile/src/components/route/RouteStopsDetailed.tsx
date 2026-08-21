import React, { useState } from 'react';
import { View, Text, StyleSheet, Pressable, Modal } from 'react-native';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { formatBlockKey, type BagGroup } from './RouteStopsList';
import { BagGroups, bagsFromTbas } from './BagStopBody';
import { resolveStopUrgency, cutoffChipText, type CutoffState } from './stopUrgency';

/** Rich per-stop drill-down for the crew detail page (ADR-216 phase 2 + 3).
 *
 * Each stop shows house# / street, package count, classification + building-type
 * chips (with cold-start defaults), the FULL TBAs, and a cutoff-urgency accent
 * bar + time chip. The accent bar colour is a now-relative gradient computed
 * client-side (stopUrgency.ts) from the server's cutoff facts. An info affordance
 * opens a bottom sheet with the operational note + full hours.
 * Grouped by block_key (the "segment" label). Reused by My Route later.
 */

export type DetailedStop = {
  block_key: string;
  address: string;
  tba_numbers: string[];
  bags?: BagGroup[];               // ADR-230: bag-grouped TBAs + color
  package_count: number;
  workload_class: string | null;   // bulk_drop | standard | high_touch | high_wait
  building_type: string | null;    // doorman | elevator | walkup | biz_freight | …
  lifecycle: string;               // current | remaining | completed

  // Phase 3 — hours, note, cutoff facts (all optional; cold-start → null).
  opens_at?: string | null;
  closes_at?: string | null;
  break_start?: string | null;
  break_end?: string | null;
  days_open?: string[] | null;
  operational_note?: string | null;
  troublesome_score?: number | null;
  cutoff_state?: CutoffState;
  cutoff_at?: string | null;
  reopens_at?: string | null;
  minutes_to_cutoff?: number | null;
};

// workload_class → { label, tone-color key }. high_wait/high_touch are the
// attention classes; standard/bulk_drop are calm.
const WORKLOAD_META: Record<string, { label: string; tone: 'danger' | 'warning' | 'info' | 'muted' }> = {
  high_wait:   { label: 'High wait',  tone: 'danger' },
  high_touch:  { label: 'High touch', tone: 'warning' },
  standard:    { label: 'Standard',   tone: 'info' },
  bulk_drop:   { label: 'Bulk drop',  tone: 'muted' },
};

// building_type enum → readable label.
const BUILDING_LABEL: Record<string, string> = {
  doorman:          'Doorman',
  receptionist:     'Reception',
  elevator:         'Elevator',
  walkup:           'Walk-up',
  mailroom:         'Mailroom',
  biz_freight:      'Freight',
  biz_security:     'Security',
  biz_loading_dock: 'Loading dock',
};

// Cold-start defaults (ADR-216 Phase 3): a stop with no profile still renders
// chips so the list isn't ragged. Unconfirmed type, Standard workload.
const COLD_TYPE_LABEL = 'Unconfirmed';
const COLD_WL_LABEL   = 'Standard';

function toneColor(tone: 'danger' | 'warning' | 'info' | 'muted', c: ThemeColors) {
  switch (tone) {
    case 'danger':  return { bg: c.dangerLight,  fg: c.danger };
    case 'warning': return { bg: c.warningLight, fg: c.warning };
    case 'info':    return { bg: c.infoLight,    fg: c.info };
    default:        return { bg: c.surfaceMuted, fg: c.mutedForeground };
  }
}

function Chip({ label, bg, fg }: { label: string; bg: string; fg: string }) {
  return (
    <View style={{ backgroundColor: bg, borderRadius: radius.xs, paddingHorizontal: spacing.xs + 1, paddingVertical: 1 }}>
      <Text style={{ fontSize: 10, fontWeight: fontWeight.bold, color: fg, letterSpacing: 0.3 }}>{label}</Text>
    </View>
  );
}

type Section = { block_key: string; stops: DetailedStop[] };

function groupByBlock(stops: DetailedStop[]): Section[] {
  const sections: Section[] = [];
  const byKey = new Map<string, Section>();
  for (const stop of stops) {
    let section = byKey.get(stop.block_key);
    if (!section) {
      section = { block_key: stop.block_key, stops: [] };
      byKey.set(stop.block_key, section);
      sections.push(section);
    }
    section.stops.push(stop);
  }
  return sections;
}

// Whether a stop carries any building detail worth an info sheet.
function hasDetail(s: DetailedStop): boolean {
  return !!(s.operational_note || s.opens_at || s.closes_at || s.break_start);
}

export default function RouteStopsDetailed({
  stops, c, urgentWindow = 60, cautionWindow = 60,
}: {
  stops: DetailedStop[];
  c: ThemeColors;
  urgentWindow?: number;
  cautionWindow?: number;
}) {
  const [sheet, setSheet] = useState<DetailedStop | null>(null);

  return (
    <View style={{ gap: spacing.sm }}>
      {groupByBlock(stops).map(section => (
        <View key={section.block_key}>
          {/* Segment label (block_key) */}
          <View style={{
            backgroundColor: c.primaryLight, borderRadius: radius.xs, alignSelf: 'flex-start',
            paddingHorizontal: spacing.xs + 2, paddingVertical: 2, marginBottom: spacing.xs,
          }}>
            <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: c.primary, letterSpacing: 0.4 }}>
              {formatBlockKey(section.block_key)}
            </Text>
          </View>

          {section.stops.map((stop, i) => {
            const wl = stop.workload_class ? WORKLOAD_META[stop.workload_class] : null;
            const wlColor = wl ? toneColor(wl.tone, c) : toneColor('muted', c);
            const wlLabel = wl ? wl.label : COLD_WL_LABEL;
            const bt = stop.building_type ? (BUILDING_LABEL[stop.building_type] ?? stop.building_type) : COLD_TYPE_LABEL;

            // House number leads (the scan target — the street repeats down a
            // block and is already in the segment label).
            const m = /^\s*(\d+[A-Za-z-]*)\s+(.*)$/.exec(stop.address || '');
            const houseNo = m ? m[1] : (stop.address || '');
            const street = m ? m[2] : '';

            // Cutoff-urgency accent bar (now-relative gradient) + time chip.
            const state = (stop.cutoff_state ?? 'none') as CutoffState;
            const urg = resolveStopUrgency(state, stop.minutes_to_cutoff, urgentWindow, cautionWindow);
            const chip = cutoffChipText(state, stop.cutoff_at, stop.reopens_at);
            const isUrgent = state === 'closed' || state === 'on_break' ||
              (state === 'future' && stop.minutes_to_cutoff != null && stop.minutes_to_cutoff <= urgentWindow);
            const showInfo = hasDetail(stop);

            return (
              <View
                key={`${section.block_key}:${stop.address}`}
                style={{
                  flexDirection: 'row',
                  borderTopWidth: i === 0 ? 0 : StyleSheet.hairlineWidth,
                  borderTopColor: c.border,
                  paddingVertical: spacing.sm,
                }}
              >
                {/* Left accent bar — cutoff gradient colour (blue when no cutoff). */}
                <View style={{ width: isUrgent ? 4 : 3, borderRadius: 2, backgroundColor: urg.color, marginRight: spacing.sm }} />
                <View style={{ flex: 1 }}>
                  {/* Header: house# bold inline, street muted, pkg count; info icon */}
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground, fontVariant: ['tabular-nums'] }}>
                      {houseNo}
                    </Text>
                    {street ? (
                      <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginLeft: spacing.xs, flexShrink: 1 }} numberOfLines={1}>
                        {street}
                      </Text>
                    ) : null}
                    <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground, marginLeft: 'auto', paddingLeft: spacing.xs }}>
                      ({stop.package_count})
                    </Text>
                    {showInfo && (
                      <Pressable
                        onPress={() => setSheet(stop)}
                        hitSlop={8}
                        style={{ marginLeft: spacing.xs, width: 18, height: 18, borderRadius: 9, borderWidth: 1.5, borderColor: c.mutedForeground, alignItems: 'center', justifyContent: 'center' }}
                      >
                        <Text style={{ fontSize: 11, fontWeight: fontWeight.bold, color: c.mutedForeground }}>i</Text>
                      </Pressable>
                    )}
                  </View>

                  {/* Cutoff time chip — coloured to match the accent when urgent. */}
                  {chip && (
                    <View style={{ flexDirection: 'row', marginTop: 4 }}>
                      <View style={{ backgroundColor: urg.color + '22', borderRadius: radius.xs, paddingHorizontal: spacing.xs + 1, paddingVertical: 1, flexDirection: 'row', alignItems: 'center' }}>
                        <Text style={{ fontSize: 11, fontWeight: fontWeight.bold, color: urg.color, letterSpacing: 0.2 }}>
                          {state === 'closed' ? '⚠ ' : state === 'on_break' ? '⏸ ' : '⏰ '}{chip}
                        </Text>
                      </View>
                    </View>
                  )}

                  {/* Classification + building-type chips (cold-start defaults render too). */}
                  <View style={{ flexDirection: 'row', gap: spacing.xs, marginTop: 4, flexWrap: 'wrap' }}>
                    <Chip label={wlLabel} bg={wlColor.bg} fg={wlColor.fg} />
                    <Chip label={bt} bg={c.surfaceMuted} fg={c.foreground} />
                    {stop.troublesome_score != null && stop.troublesome_score >= 2.5 && (
                      <Chip label="⚑ Troublesome" bg={c.dangerLight} fg={c.danger} />
                    )}
                  </View>

                  {/* Bag-grouped, full TBAs (ADR-230): colored number pill + TBAs. */}
                  <BagGroups bags={stop.bags?.length ? stop.bags : bagsFromTbas(stop.tba_numbers)} c={c} />
                </View>
              </View>
            );
          })}
        </View>
      ))}

      {/* Info bottom sheet — operational note + full hours. */}
      <StopInfoSheet stop={sheet} c={c} onClose={() => setSheet(null)} />
    </View>
  );
}

const DAY_LABEL: Record<string, string> = {
  Mon: 'Mon', Tue: 'Tue', Wed: 'Wed', Thu: 'Thu', Fri: 'Fri', Sat: 'Sat', Sun: 'Sun',
};

function hoursLine(s: DetailedStop): string | null {
  if (!s.opens_at && !s.closes_at) return null;
  const open = s.opens_at ?? '—';
  const close = s.closes_at ?? '—';
  return `${open} – ${close}`;
}

function StopInfoSheet({ stop, c, onClose }: { stop: DetailedStop | null; c: ThemeColors; onClose: () => void }) {
  if (!stop) return null;
  const hours = hoursLine(stop);
  const days = stop.days_open?.length ? stop.days_open.map(d => DAY_LABEL[d] ?? d).join(' · ') : null;
  const bt = stop.building_type ? (BUILDING_LABEL[stop.building_type] ?? stop.building_type) : COLD_TYPE_LABEL;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={{ flex: 1, backgroundColor: '#00000066', justifyContent: 'flex-end' }} onPress={onClose}>
        <Pressable
          onPress={() => {}}
          style={{ backgroundColor: c.card, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.lg, gap: spacing.md }}
        >
          <View style={{ width: 36, height: 4, borderRadius: 2, backgroundColor: c.border, alignSelf: 'center' }} />
          <Text style={{ fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground }}>
            {stop.address}
          </Text>
          <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground }}>{bt}</Text>

          {hours && (
            <View style={{ gap: 2 }}>
              <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: c.mutedForeground, letterSpacing: 0.4 }}>HOURS</Text>
              <Text style={{ fontSize: fontSize.base, color: c.foreground, fontVariant: ['tabular-nums'] }}>{hours}</Text>
              {(stop.break_start && stop.break_end) && (
                <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground }}>
                  Break {stop.break_start} – {stop.break_end}
                </Text>
              )}
              {days && <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground }}>{days}</Text>}
            </View>
          )}

          {stop.operational_note ? (
            <View style={{ gap: 2 }}>
              <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: c.mutedForeground, letterSpacing: 0.4 }}>OPERATIONAL NOTE</Text>
              <Text style={{ fontSize: fontSize.base, color: c.foreground, lineHeight: 22 }}>{stop.operational_note}</Text>
            </View>
          ) : (
            <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground, fontStyle: 'italic' }}>No operational note yet.</Text>
          )}

          <Pressable
            onPress={onClose}
            style={{ marginTop: spacing.xs, backgroundColor: c.surfaceMuted, borderRadius: radius.md, paddingVertical: spacing.sm, alignItems: 'center' }}
          >
            <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground }}>Close</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
