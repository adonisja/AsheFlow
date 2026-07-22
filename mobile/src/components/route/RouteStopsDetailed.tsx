import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { formatBlockKey } from './RouteStopsList';

/** Rich per-stop drill-down for the crew detail page (ADR-216 phase 2).
 *
 * Extends RouteStopsList's block-grouped double-column TBA layout with per-stop
 * classification (workload_class) + building type chips and a package count.
 * Grouped by block_key (the "segment" label). Reused by My Route later.
 */

export type DetailedStop = {
  block_key: string;
  address: string;
  tba_numbers: string[];
  package_count: number;
  workload_class: string | null;   // bulk_drop | standard | high_touch | high_wait
  building_type: string | null;    // doorman | elevator | walkup | biz_freight | …
  lifecycle: string;               // current | remaining | completed
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

export default function RouteStopsDetailed({ stops, c }: { stops: DetailedStop[]; c: ThemeColors }) {
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
            const wlColor = wl ? toneColor(wl.tone, c) : null;
            const bt = stop.building_type ? (BUILDING_LABEL[stop.building_type] ?? stop.building_type) : null;
            // House number leads (the scan target — the street repeats down a
            // block and is already in the segment label). The accent bar is tinted
            // by classification when profiled, neutral otherwise.
            const m = /^\s*(\d+[A-Za-z-]*)\s+(.*)$/.exec(stop.address || '');
            const houseNo = m ? m[1] : (stop.address || '');
            const street = m ? m[2] : '';
            const accent = wlColor ? wlColor.fg : c.border;
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
                {/* Left accent bar (classification tint or neutral) */}
                <View style={{ width: 3, borderRadius: 2, backgroundColor: accent, marginRight: spacing.sm }} />
                <View style={{ flex: 1 }}>
                  {/* Header: house# bold inline, street muted, pkg count; chips right */}
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
                      {stop.package_count} pkg{stop.package_count === 1 ? '' : 's'}
                    </Text>
                  </View>
                  {(wl || bt) && (
                    <View style={{ flexDirection: 'row', gap: spacing.xs, marginTop: 4, flexWrap: 'wrap' }}>
                      {wl && wlColor && <Chip label={wl.label} bg={wlColor.bg} fg={wlColor.fg} />}
                      {bt && <Chip label={bt} bg={c.surfaceMuted} fg={c.foreground} />}
                    </View>
                  )}
                  {/* TBAs — de-emphasized reference, 2-column, monospaced */}
                  <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 4 }}>
                    {stop.tba_numbers.map(tba => (
                      <Text
                        key={tba}
                        style={{
                          width: '50%', fontSize: fontSize.xs, color: c.mutedForeground,
                          fontVariant: ['tabular-nums'], lineHeight: 18,
                        }}
                        numberOfLines={1}
                      >
                        ··{tba.slice(-8)}
                      </Text>
                    ))}
                  </View>
                </View>
              </View>
            );
          })}
        </View>
      ))}
    </View>
  );
}
