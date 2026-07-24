import React from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import type { BagGroup } from './RouteStopsList';

/** Shared stop body used by every route breakdown surface (ADR-230):
 *  - address header: house# bold + street muted + (N) right-aligned muted count
 *  - one row per BAG: a number-only pill tinted the bag's physical color
 *    (neutral gray when color is null), then that bag's FULL TBAs as plain
 *    monospaced text (tabular-nums, NOT pills, NOT truncated).
 *
 * When a stop has no `bags` (route stops written before ADR-230), the caller
 * passes a single fallback group built from the flat tba_numbers.
 */

export function splitHouseStreet(address: string): { houseNo: string; street: string } {
  const m = /^\s*(\d+[A-Za-z-]*)\s+(.*)$/.exec(address || '');
  return m ? { houseNo: m[1], street: m[2] } : { houseNo: address || '', street: '' };
}

/** A single bag's number-only pill, tinted its physical color. */
export function BagPill({ bag, c }: { bag: BagGroup; c: ThemeColors }) {
  const tint = bag.bag_color || c.mutedForeground;   // null color → neutral
  return (
    <View style={{
      backgroundColor: tint + '22', borderRadius: radius.xs, borderWidth: 1, borderColor: tint + '66',
      paddingHorizontal: spacing.xs + 1, paddingVertical: 1, alignSelf: 'flex-start',
    }}>
      <Text style={{ fontSize: 11, fontWeight: fontWeight.bold, color: tint, fontVariant: ['tabular-nums'], letterSpacing: 0.3 }}>
        {bag.bag_id}
      </Text>
    </View>
  );
}

export function bagsFromTbas(tba_numbers: string[]): BagGroup[] {
  // Fallback for pre-ADR-230 stops with no bag grouping: one "unknown" group.
  return [{ bag_id: '—', bag_color: null, tba_numbers: tba_numbers ?? [] }];
}

/** The address header row: house# + street + right-aligned bracketed count. */
export function StopAddressHeader({
  address, count, c, children,
}: {
  address: string; count: number; c: ThemeColors; children?: React.ReactNode;
}) {
  const { houseNo, street } = splitHouseStreet(address);
  return (
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
        ({count})
      </Text>
      {children}
    </View>
  );
}

/** The bag groups block: per bag → colored number pill + full TBAs. */
export function BagGroups({
  bags, c, onTbaPress,
}: {
  bags: BagGroup[]; c: ThemeColors;
  onTbaPress?: (tba: string) => void;   // MyRoute uses this to flag a package
}) {
  return (
    <View style={{ marginTop: 4, gap: 4 }}>
      {bags.map(bag => (
        <View key={bag.bag_id} style={{ flexDirection: 'row', alignItems: 'flex-start', gap: spacing.sm }}>
          <BagPill bag={bag} c={c} />
          <View style={{ flex: 1, flexDirection: 'row', flexWrap: 'wrap' }}>
            {bag.tba_numbers.map(tba => {
              const label = (
                <Text
                  style={{ width: '50%', fontSize: fontSize.xs, color: c.mutedForeground, fontVariant: ['tabular-nums'], lineHeight: 18 }}
                  numberOfLines={1}
                >
                  {tba}
                </Text>
              );
              return onTbaPress ? (
                <TouchableOpacity key={tba} style={{ width: '50%' }} onPress={() => onTbaPress(tba)} onLongPress={() => onTbaPress(tba)}>
                  <Text style={{ fontSize: fontSize.xs, color: c.foreground, fontVariant: ['tabular-nums'], lineHeight: 18 }} numberOfLines={1}>
                    {tba}
                  </Text>
                </TouchableOpacity>
              ) : (
                <React.Fragment key={tba}>{label}</React.Fragment>
              );
            })}
          </View>
        </View>
      ))}
    </View>
  );
}
