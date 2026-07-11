import React from 'react';
import { View, Text } from 'react-native';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

/** Grouped route drill-down (ADR-194): block section → address → TBA grid.
 *
 * `stops` is the server's delivered-set list, already sorted (blocks ascending,
 * house numbers ascending within a block) — grouping here just walks it in
 * order. Routes that predate the stops column pass null and the caller falls
 * back to its flat address list.
 */

export type RouteStop = {
  block_key: string;
  address: string;
  tba_numbers: string[];
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
  const sections: BlockSection[] = [];
  for (const stop of stops) {
    const last = sections[sections.length - 1];
    if (last && last.block_key === stop.block_key) last.stops.push(stop);
    else sections.push({ block_key: stop.block_key, stops: [stop] });
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
          {section.stops.map(stop => (
            <View key={stop.address} style={{ marginBottom: spacing.xs + 2 }}>
              <Text style={{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.foreground }}>
                {stop.address}
              </Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 2 }}>
                {stop.tba_numbers.map(tba => (
                  <Text
                    key={tba}
                    style={{
                      width: '50%', fontSize: fontSize.xs, color: c.mutedForeground,
                      fontVariant: ['tabular-nums'], lineHeight: 17,
                    }}
                    numberOfLines={1}
                  >
                    …{tba.slice(-8)}
                  </Text>
                ))}
              </View>
            </View>
          ))}
        </View>
      ))}
    </View>
  );
}
