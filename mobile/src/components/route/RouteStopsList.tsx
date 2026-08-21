import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { StopAddressHeader, BagGroups, bagsFromTbas } from './BagStopBody';

/** Grouped route drill-down (ADR-194): block section → address → TBA grid.
 *
 * `stops` is the server's delivered-set list, already sorted (blocks ascending,
 * house numbers ascending within a block) — grouping here just walks it in
 * order. Routes that predate the stops column pass null and the caller falls
 * back to its flat address list.
 */

// ADR-230: TBAs grouped by physical bag, with the bag's color tint.
export type BagGroup = {
  bag_id: string;
  bag_color?: string | null;   // hex from backend; null → neutral pill
  tba_numbers: string[];
};

export type RouteStop = {
  block_key: string;
  address: string;
  tba_numbers: string[];
  bags?: BagGroup[];           // ADR-230; falls back to a single group when absent
};

/** "W_44_St_300" → "WEST 44 ST · 300 BLOCK"; "9_Ave_800" → "9 AVE · 800 BLOCK". */
export function formatBlockKey(bk: string): string {
  const parts = bk.split('_');
  const DIR: Record<string, string> = { W: 'WEST', E: 'EAST', N: 'NORTH', S: 'SOUTH' };
  if (parts.length === 4 && DIR[parts[0]]) {
    return `${DIR[parts[0]]} ${parts[1]} ${parts[2].toUpperCase()} · ${parts[3]} BLOCK`;
  }
  if (parts.length === 3) {
    return `${parts[0]} ${parts[1].toUpperCase()} · ${parts[2]} BLOCK`;
  }
  return bk;
}

type BlockSection = { block_key: string; stops: RouteStop[] };

function groupByBlock(stops: RouteStop[]): BlockSection[] {
  // Group by block_key GLOBALLY, not just consecutively: the server sort can
  // interleave a block_key with others (e.g. 6_Ave_1000 addresses split around
  // W_46_St_* under the sort), which would otherwise produce two sections with
  // the same key → a React duplicate-key crash. First appearance sets order.
  const sections: BlockSection[] = [];
  const byKey = new Map<string, BlockSection>();
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

export default function RouteStopsList({ stops, c }: { stops: RouteStop[]; c: ThemeColors }) {
  return (
    <View style={{ gap: spacing.sm }}>
      {groupByBlock(stops).map(section => (
        <View key={section.block_key}>
          <View style={{
            backgroundColor: c.primaryLight, borderRadius: radius.xs, alignSelf: 'flex-start',
            paddingHorizontal: spacing.xs + 2, paddingVertical: 2, marginBottom: spacing.xs,
          }}>
            <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.bold, color: c.primary, letterSpacing: 0.4 }}>
              {formatBlockKey(section.block_key)}
            </Text>
          </View>
          {section.stops.map((stop, i) => {
            // ADR-230: bag-grouped, full TBAs. Fall back to a single group for
            // stops written before bags existed.
            const bags = stop.bags?.length ? stop.bags : bagsFromTbas(stop.tba_numbers);
            return (
              <View
                key={`${section.block_key}:${stop.address}`}
                style={{
                  borderTopWidth: i === 0 ? 0 : StyleSheet.hairlineWidth,
                  borderTopColor: c.border,
                  paddingVertical: spacing.sm,
                }}
              >
                <StopAddressHeader address={stop.address} count={stop.tba_numbers.length} c={c} />
                <BagGroups bags={bags} c={c} />
              </View>
            );
          })}
        </View>
      ))}
    </View>
  );
}
