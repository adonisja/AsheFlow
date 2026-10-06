import { useEffect, useState } from 'react';
import { AccessibilityInfo } from 'react-native';

/**
 * Does the OS want motion suppressed, as RENDER STATE?
 *
 * WHY THIS IS NOT `primitives.useReduceMotion`
 * ============================================
 *
 * There is already a hook for this, and it returns a REF on purpose. Its comment
 * explains why, and that reasoning is correct for its callers:
 *
 *   > A REF, not state. Nothing needs to re-render when this resolves — it is
 *   > only read at animation time — and as state it recreates every callback
 *   > that depends on it. In CompanyStandingCard that chain (animateChevron ->
 *   > load -> the effect calling it) shifted the hook order mid-mount and
 *   > crashed with "Rendered more hooks than during the previous render".
 *
 * Both halves of that are about a value read INSIDE an animation callback. The
 * ticker's need is the opposite: with motion reduced it renders a completely
 * different subtree — a static, expandable row instead of a scrolling strip
 * (ADR-487 D4b). A ref cannot drive that, because nothing re-renders when the
 * setting resolves, so the first paint would always be the animated version and
 * would stay that way until some unrelated state change.
 *
 * So this is state, and the crash it has to avoid is real rather than
 * hypothetical. Two things keep it safe:
 *
 *   * **Nothing here feeds a `useCallback` dependency.** The value is read in
 *     the render body to choose a subtree, not captured by a callback that
 *     other hooks then depend on. That chain is what shifted the hook order in
 *     CompanyStandingCard, and it does not exist in the ticker.
 *   * **The subtrees are siblings, not conditional hook sites.** Both branches
 *     are returned from the same component, and the component calls its hooks
 *     unconditionally before either branch is chosen.
 *
 * Deliberately a SEPARATE hook rather than changing the existing one: converting
 * `useReduceMotion` to state would reintroduce the exact crash its comment
 * documents, in three call sites that are correct as they are.
 *
 * SUBSCRIBED, NOT READ ONCE
 * =========================
 *
 * ADR-487 D4b names this: the setting can change while the app is open, and a
 * dispatcher who turns reduce-motion ON mid-shift — plausibly BECAUSE the ticker
 * is bothering them — would keep the scrolling until the next cold start.
 */
export function useReducedMotionState(): boolean {
  // Defaults to FALSE (animate). Defaulting to "reduce" would silently disable
  // motion for the first frame on every launch, and for anyone whose platform
  // does not answer — the opposite of a progressive enhancement.
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    let alive = true;

    AccessibilityInfo.isReduceMotionEnabled().then(v => {
      if (alive) setReduced(v);
    }).catch(() => {
      // An unsupported platform must not take out the ticker; it just animates.
    });

    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', v => {
      setReduced(v);
    });

    return () => {
      alive = false;
      // `?.remove?.()` matching the three existing call sites: the subscription
      // shape differs across RN versions and this project is on bare 0.85.
      sub?.remove?.();
    };
  }, []);

  return reduced;
}
