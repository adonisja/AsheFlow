/**
 * The DSP's Amazon standing — a shared fact, shown to every role.
 *
 * Tier 1 in docs/SCORECARD_ACCESS_MODEL.md: `GET /scorecards/company/current`
 * is gated to ALL roles and returns no PII whatsoever — a week, a standing, and
 * the direction of travel. A walker learns where the company stands without
 * seeing anyone's individual numbers, which is the whole reason this is a
 * separate endpoint from the Tier 3 roster.
 *
 * ## Folding
 *
 * Collapsed to a single summary line by default once you have seen a given
 * week, because this is context on someone else's screen — it should not cost
 * a third of the home screen every morning.
 *
 * It unfolds ITSELF, once, when the week changes. Publishing a new scorecard is
 * the one moment this data is worth interrupting for, and the user should not
 * have to know to go looking. After that first look the card remembers whatever
 * the user last chose, per week.
 *
 * No live push. A newly published card unfolds on the next open or pull-to-
 * refresh, which costs nothing; SSE would need a new event type, an RN stream
 * client and reconnect handling to save a few minutes of latency on a weekly
 * event.
 *
 * ## Platform
 *
 * `LayoutAnimation` rather than Reanimated: the app has no Reanimated
 * dependency and adding a native module + Babel plugin for one height change is
 * not worth it. LayoutAnimation runs on the native thread and works under the
 * New Architecture via `configureNextLayoutAnimation`. Motion is tuned per
 * platform — iOS springs, Android eases — and skipped entirely when the user
 * has asked for reduced motion, all inside `useLayoutTransition`.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AccessibilityInfo, ActivityIndicator, Animated,
  StyleSheet, Text, TouchableOpacity, View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, spring, type ThemeColors } from '@theme/index';
import { useLayoutTransition } from '@hooks/useLayoutTransition';
import { tick } from '@components/ui/primitives';

// The old-architecture LayoutAnimation opt-in was removed here: it is a no-op
// under the New Architecture and logged a warning on every launch. See
// hooks/useLayoutTransition.ts for the full reasoning.

const SEEN_KEY = 'asheflow.companyStanding.seenWeek';
const FOLD_KEY = 'asheflow.companyStanding.folded';

type Standing = {
  week: string | null;
  standing: string | null;
  previous_standing: string | null;
  /** improved | declined | unchanged | null */
  direction: string | null;
  /** Weeks held at the CURRENT standing, not a total. */
  consecutive_weeks: number;
  has_data: boolean;
};

/** Amazon's standings, best to worst. Semantic colours (ADR-207) so they track
 *  the theme rather than hard-coding light/dark values. */
function standingColor(s: string | null, c: ThemeColors): string {
  switch ((s || '').toLowerCase()) {
    case 'fantastic':      return c.success;
    case 'great':          return c.info;
    case 'fair':           return c.gold;
    case 'poor':           return c.warning;
    case 'at risk':
    case 'at_risk':        return c.danger;
    default:               return c.mutedForeground;
  }
}

function directionLabel(d: string | null, prev: string | null): string | null {
  if (d === 'improved') return prev ? `Up from ${prev}` : 'Improved';
  if (d === 'declined') return prev ? `Down from ${prev}` : 'Declined';
  return null;
}


export default function CompanyStandingCard() {
  const c = useColors();
  const s = styles(c);

  const [data, setData] = useState<Standing | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [folded, setFolded] = useState(true);
  // A REF, not state: as state this recreated animateChevron -> load -> the
  // effect that calls it, changing the hook chain mid-mount and crashing with
  // "Rendered more hooks than during the previous render". Nothing needs to
  // re-render when this resolves — it is only read at animation time.
  const reduceMotion = useRef(false);

  const chevron = useRef(new Animated.Value(0)).current;   // 0 folded, 1 open
  const animateNext = useLayoutTransition();

  // Respect the OS accessibility setting. An animation that ignores
  // reduce-motion is a bug, not a flourish.
  useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled().then(v => { if (alive) reduceMotion.current = v; });
    const sub = AccessibilityInfo.addEventListener(
      'reduceMotionChanged', v => { reduceMotion.current = v; });
    return () => { alive = false; sub?.remove?.(); };
  }, []);

  const animateChevron = useCallback((open: boolean) => {
    if (reduceMotion.current) { chevron.setValue(open ? 1 : 0); return; }
    Animated.spring(chevron, {
      toValue: open ? 1 : 0,
      useNativeDriver: true,      // off the JS thread, like the rest of the app
      ...spring.subtle,
    }).start();
  }, [chevron]);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get<Standing>('/scorecards/company/current');
      const next = res.data;
      setData(next);
      setFailed(false);

      if (next?.has_data && next.week) {
        const [seenWeek, storedFold] = await Promise.all([
          AsyncStorage.getItem(SEEN_KEY),
          AsyncStorage.getItem(FOLD_KEY),
        ]);

        // A week we have not shown before: unfold once, unprompted. This is the
        // "new card published" case — the only moment the data is worth
        // interrupting for.
        if (seenWeek !== next.week) {
          setFolded(false);
          animateChevron(true);
          await AsyncStorage.multiSet([[SEEN_KEY, next.week], [FOLD_KEY, 'false']]);
        } else {
          const isFolded = storedFold !== 'false';
          setFolded(isFolded);
          animateChevron(!isFolded);
        }
      }
    } catch {
      // Context, not the point of the screen — a failure here must never put an
      // error banner over whatever the user actually opened.
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [animateChevron]);

  useEffect(() => { void load(); }, [load]);

  const toggle = useCallback(() => {
    const next = !folded;
    animateNext();   // reduce-motion handled inside the hook
    // A short tick confirms the tap without the user looking — useful with
    // gloves on in a van. Shared `tick()` rather than a second raw
    // Vibration.vibrate: unguarded, it throws when VIBRATE is unavailable and
    // takes the toggle down with it (crashed "Mark As Present", 2026-08-04).
    tick();
    setFolded(next);
    animateChevron(!next);
    void AsyncStorage.setItem(FOLD_KEY, String(next));
  }, [folded, animateNext, animateChevron]);

  if (loading) {
    return (
      <View style={[s.card, s.centered]}>
        <ActivityIndicator color={c.primary} />
      </View>
    );
  }

  // No scorecard yet, or the fetch failed. Render nothing rather than an empty
  // shell — this is supplementary context on someone else's screen.
  if (failed || !data?.has_data) return null;

  const tone = standingColor(data.standing, c);
  const dir = directionLabel(data.direction, data.previous_standing);
  const rotate = chevron.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '180deg'] });

  return (
    <View style={s.card}>
      <TouchableOpacity
        onPress={toggle}
        activeOpacity={0.7}
        accessibilityRole="button"
        accessibilityState={{ expanded: !folded }}
        accessibilityLabel={
          folded
            ? `Company standing ${data.standing ?? 'unknown'}. Double tap to expand.`
            : 'Company standing. Double tap to collapse.'
        }
        // A thin summary row is a small tap target; widen it without changing
        // the visual density.
        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
      >
        <View style={s.row}>
          <Text style={s.label}>Company standing</Text>
          <View style={s.rowRight}>
            {/* Folded, the standing itself IS the summary — collapsing to a
                bare chevron would hide the one fact worth glancing at. */}
            {folded && (
              <Text style={[s.summary, { color: tone }]} numberOfLines={1}>
                {data.standing ?? '—'}
              </Text>
            )}
            <Animated.Text style={[s.chevron, { transform: [{ rotate }] }]}>⌄</Animated.Text>
          </View>
        </View>
      </TouchableOpacity>

      {!folded && (
        <View style={s.body}>
          {data.week && <Text style={s.week}>{data.week}</Text>}
          <Text style={[s.standing, { color: tone }]}>{data.standing ?? '—'}</Text>
          <View style={s.row}>
            {dir && <Text style={s.meta}>{dir}</Text>}
            {data.consecutive_weeks > 1 && (
              <Text style={s.meta}>{data.consecutive_weeks} weeks running</Text>
            )}
          </View>
        </View>
      )}
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  card: {
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginBottom: spacing.md,
    overflow: 'hidden',
  },
  centered: { alignItems: 'center', justifyContent: 'center', minHeight: 64 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  rowRight: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, flexShrink: 1 },
  label: {
    color: c.mutedForeground,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.medium,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  summary: { fontSize: fontSize.base, fontWeight: fontWeight.semibold, flexShrink: 1 },
  chevron: { color: c.mutedForeground, fontSize: fontSize.md, lineHeight: fontSize.md },
  body: { paddingTop: spacing.xs, gap: spacing.xs },
  week: { color: c.mutedForeground, fontSize: fontSize.sm },
  standing: { fontSize: fontSize.xl, fontWeight: fontWeight.bold },
  meta: { color: c.mutedForeground, fontSize: fontSize.sm },
});
