/**
 * Animate the NEXT layout change — expand/collapse, list add/remove.
 *
 * ## Why this exists
 *
 * 3 of 34 screens animated anything, and eight of the rest have expand/collapse
 * that snaps instantly. When a section appears with no transition the user has
 * to re-scan the page to work out what changed and where it came from; the
 * motion is doing information work, not decoration. That is the bar for adding
 * it — a fade on a button is taste, this is not.
 *
 * ## Usage
 *
 *     const animateNext = useLayoutTransition();
 *
 *     const toggle = (role: string) => {
 *       animateNext();                       // call BEFORE the setState
 *       setExpanded(e => ({ ...e, [role]: !e[role] }));
 *     };
 *
 * `LayoutAnimation` applies to the next commit, so it must be called before the
 * state update, not after.
 *
 * ## Why not Reanimated
 *
 * Measured in plan 1.2: the app has no gesture-driven or scroll-linked motion,
 * which is what Reanimated's worklets are for. `LayoutAnimation` runs on the
 * native thread and needs no native module or Babel plugin. If a swipe-to-
 * complete or draggable sort ever lands, revisit — this is not a permanent
 * position, it is a proportionate one.
 *
 * ## Reduce-motion
 *
 * Honoured here, centrally, so no caller has to remember (plan §4 rule 5).
 * When the OS asks for reduced motion this becomes a no-op and layout snaps —
 * which is the correct behaviour, not a degraded one.
 */
import { useCallback, useEffect, useRef } from 'react';
import { AccessibilityInfo, LayoutAnimation, Platform, UIManager } from 'react-native';
import { duration, layoutSpring } from '@theme/index';

// LayoutAnimation is opt-in on Android's old architecture. Harmless if another
// module already enabled it.
if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) {
  UIManager.setLayoutAnimationEnabledExperimental(true);
}

/**
 * iOS springs, Android eases. Matching each platform's own idiom is what makes
 * a transition read as native rather than generic (plan §4 rule 7).
 *
 * `create`/`delete` fade rather than scale: content appearing in a list should
 * arrive, not pop.
 */
const CONFIG = Platform.select({
  ios: {
    duration: duration.normal,
    create: { type: LayoutAnimation.Types.easeInEaseOut, property: LayoutAnimation.Properties.opacity },
    update: { type: LayoutAnimation.Types.spring, ...layoutSpring },
    delete: { type: LayoutAnimation.Types.easeInEaseOut, property: LayoutAnimation.Properties.opacity },
  },
  default: {
    duration: duration.fast,
    create: { type: LayoutAnimation.Types.easeInEaseOut, property: LayoutAnimation.Properties.opacity },
    update: { type: LayoutAnimation.Types.easeInEaseOut },
    delete: { type: LayoutAnimation.Types.easeInEaseOut, property: LayoutAnimation.Properties.opacity },
  },
})!;

export function useLayoutTransition() {
  const reduceMotion = useRef(false);

  useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled().then(v => { if (alive) reduceMotion.current = v; });
    const sub = AccessibilityInfo.addEventListener(
      'reduceMotionChanged',
      v => { reduceMotion.current = v; },
    );
    return () => { alive = false; sub?.remove?.(); };
  }, []);

  return useCallback(() => {
    if (reduceMotion.current) return;
    LayoutAnimation.configureNext(CONFIG);
  }, []);
}
