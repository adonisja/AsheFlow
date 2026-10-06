import React, { useEffect, useRef, useState } from 'react';
import {
  Animated, Easing, LayoutChangeEvent, Pressable, StyleSheet, Text, View,
} from 'react-native';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, type ThemeColors } from '@theme/index';
import { useReducedMotionState } from '../../hooks/useReducedMotionState';

/**
 * Events that happened, scrolling past (ADR-487 D4b, mobile half).
 *
 * THE TRADE, WHICH IS THE SAME ON BOTH SURFACES
 * =============================================
 *
 * This is NOT a space saving. ADR-275 D2 had already collapsed the
 * informational set into one row with a preview; the ticker is shorter by about
 * 14px against a control that is strictly MORE informative. The reason is the
 * last row of ADR-487 D4b's table: *noticed without looking for it.* A static
 * row in a fixed position is something people learn to stop seeing, and motion
 * in peripheral vision is picked up without directed attention — which is what
 * an announcement to a walker holding a phone in a van actually needs.
 *
 * WHAT IS DIFFERENT HERE FROM WEB
 * ===============================
 *
 * Three things, each because of the platform rather than preference:
 *
 *   * **`Animated.loop` with `useNativeDriver: true`**, not a CSS keyframe. The
 *     motion runs off the JS thread, so it survives a busy render — which on
 *     this surface means a FlatList scrolling underneath it.
 *   * **The width is MEASURED, not inferred.** Web can translate by -50% of a
 *     duplicated string because CSS knows the element's width. RN needs the
 *     measurement, so the strip renders once, measures `onLayout`, and only then
 *     starts the loop. Before the measurement arrives it shows the static row,
 *     which doubles as the loading state.
 *   * **`AccessibilityInfo`, not a media query** — and subscribed rather than
 *     read once, per D4b. See `useReducedMotionState` for why that needs its own
 *     hook rather than the existing ref-returning one.
 */
interface TickerItem {
  id: string;
  message: string;
  icon?: string;
  label?: string;
}

interface Props {
  items: TickerItem[];
  onPress?: () => void;
  onDismissAll?: () => void;
}

/** Characters per second. Matches web's 22, so the two surfaces read alike. */
const CHARS_PER_SECOND = 22;
/** A one-item ticker must not be instant. Matches web's 18s floor. */
const MIN_DURATION_MS = 18_000;

export const NotificationTicker: React.FC<Props> = ({ items, onPress, onDismissAll }) => {
  const c = useColors();
  const reduced = useReducedMotionState();
  const [expanded, setExpanded] = useState(false);
  const [stripWidth, setStripWidth] = useState(0);
  const translate = useRef(new Animated.Value(0)).current;
  const s = styles(c);

  const line = items.map(n => `${n.icon ?? '•'} ${n.message}`).join('   ·   ');

  useEffect(() => {
    // Nothing to animate until the strip has been measured, and nothing SHOULD
    // animate when the OS asked for stillness.
    if (reduced || stripWidth <= 0 || items.length === 0) {
      translate.stopAnimation();
      translate.setValue(0);
      return;
    }

    const duration = Math.max(
      MIN_DURATION_MS, (line.length / CHARS_PER_SECOND) * 1000,
    );

    translate.setValue(0);
    const loop = Animated.loop(
      Animated.timing(translate, {
        // -stripWidth, not -50%: the strip is rendered twice and this is the
        // measured width of ONE copy, so the duplicate lands exactly where the
        // original started and the loop has no visible seam.
        toValue: -stripWidth,
        duration,
        easing: Easing.linear,   // a ticker that eases is a ticker that stalls
        useNativeDriver: true,
      }),
    );
    loop.start();
    return () => loop.stop();
  }, [reduced, stripWidth, line, items.length, translate]);

  if (items.length === 0) return null;

  const newest = items[0];

  /* ---------------- reduced motion: the collapsed row ---------------- */
  // Not a degraded fallback. This is the better-detail control from ADR-487
  // D4b's table — a count plus the newest item, expandable in place — which
  // makes the reduced-motion path strictly MORE informative than the ticker.
  if (reduced) {
    return (
      <View style={s.shell}>
        <Pressable
          onPress={() => setExpanded(v => !v)}
          accessibilityRole="button"
          accessibilityState={{ expanded }}
          accessibilityLabel={
            items.length === 1
              ? `1 update: ${newest.message}`
              : `${items.length} updates. ${newest.message}`
          }
          style={s.row}
        >
          <Text style={s.icon}>{newest.icon ?? '•'}</Text>
          <Text style={s.preview} numberOfLines={1}>
            {newest.label ? `${newest.label} — ` : ''}{newest.message}
          </Text>
          {items.length > 1 && (
            <Text style={s.count}>+{items.length - 1}</Text>
          )}
          <Text style={s.chevron}>{expanded ? '▴' : '▾'}</Text>
        </Pressable>

        {expanded && (
          <View style={s.expanded}>
            {items.map(n => (
              <View key={n.id} style={s.expandedRow}>
                <Text style={s.icon}>{n.icon ?? '•'}</Text>
                <Text style={s.expandedText}>{n.message}</Text>
              </View>
            ))}
          </View>
        )}
      </View>
    );
  }

  /* ---------------- motion: the scrolling strip ---------------- */
  return (
    <Pressable
      onPress={onPress}
      onLongPress={onDismissAll}
      // The strip is a live announcement but POLITE: these are events with no
      // consequence for the reader, so interrupting a screen reader mid-sentence
      // would be exactly wrong. The URGENT region is where assertive belongs —
      // and it is not a live region at all, because it is a card to ACT on.
      accessibilityLiveRegion="polite"
      accessibilityRole="button"
      accessibilityLabel={`${items.length} update${items.length === 1 ? '' : 's'}. ${line}`}
      style={[s.shell, s.strip]}
    >
      <Animated.View
        style={[s.scroller, { transform: [{ translateX: translate }] }]}
      >
        <Text
          style={s.scrollText}
          numberOfLines={1}
          onLayout={(e: LayoutChangeEvent) => {
            const w = e.nativeEvent.layout.width;
            // Only grow: an onLayout during the animation would otherwise
            // restart the loop every frame via the effect's dependency.
            if (w > 0 && Math.abs(w - stripWidth) > 1) setStripWidth(w);
          }}
        >
          {line}
        </Text>
        {/* The duplicate exists only so the loop has no visible gap. It is
            hidden from the screen reader, which already got the whole line
            from the accessibilityLabel above. */}
        <Text
          style={s.scrollText}
          numberOfLines={1}
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
        >
          {line}
        </Text>
      </Animated.View>
    </Pressable>
  );
};

const styles = (c: ThemeColors) => StyleSheet.create({
  shell: {
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: c.border,
    backgroundColor: c.surfaceMuted,
    overflow: 'hidden',
  },
  strip: { height: 32, justifyContent: 'center' },
  scroller: { flexDirection: 'row', alignItems: 'center' },
  scrollText: {
    fontSize: fontSize.xs,
    color: c.mutedForeground,
    paddingHorizontal: spacing.md,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    // 44pt: WCAG 2.5.5, the floor `primitives.MIN_TARGET` sets for anything
    // interactive. The web row is shorter because a cursor is not a thumb.
    minHeight: 44,
  },
  icon: { fontSize: fontSize.sm },
  preview: { flex: 1, fontSize: fontSize.xs, color: c.mutedForeground },
  count: {
    fontSize: fontSize.xs,
    color: c.mutedForeground,
    fontVariant: ['tabular-nums'],
  },
  chevron: { fontSize: fontSize.xs, color: c.mutedForeground },
  expanded: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: c.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    gap: spacing.xs,
  },
  expandedRow: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.xs },
  expandedText: { flex: 1, fontSize: fontSize.xs, color: c.mutedForeground },
});
