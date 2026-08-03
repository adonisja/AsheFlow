// AsheFlow mobile design tokens
// Philosophy: same token names as the web system (index.css) for mental-model parity,
// but values are shifted vibrant + high-contrast for outdoor, sunlight-readable use
// by field staff on Android/iOS. The web palette is muted/professional for office/exec
// users — this palette is energetic and clear.

// ─── Raw palette ─────────────────────────────────────────────────────────────

// The legacy hardcoded `palette` export lived here — 51 raw values including
// #4F6BF4, the exact mobile primary that task 0.2 was meant to eliminate. It
// was a SECOND source of truth sitting directly above the generated tokens, so
// "reconciled to one value" was only half true while it existed (plan §2.6).
//
// Colour now comes from design/palette.json via generated-colors.ts. Gradient
// anchors that are not semantic tokens live in that file's `ramp` export.

// ─── Semantic color maps ──────────────────────────────────────────────────────

import type { GeneratedColors } from './generated-colors';
import { generatedLight, generatedDark } from './generated-colors';

/**
 * Colour is GENERATED from design/palette.json (plan §0.1) — see
 * design/build_tokens.py. Web and mobile drifted when both were hand-written
 * (web primary #3C64DD vs mobile #4F6BF4); one source makes that impossible.
 *
 * To change a colour: edit design/palette.json, run the generator, commit the
 * output. Contrast is verified before anything is written, so a failing value
 * cannot reach this file.
 *
 * Spacing, radius, type and motion below stay hand-owned — they never drifted,
 * and the generator has no opinion about layout.
 */
export type ThemeColors = GeneratedColors;

export const lightColors: ThemeColors = generatedLight;

export const darkColors: ThemeColors = generatedDark;

// ─── Spacing ─────────────────────────────────────────────────────────────────

export const spacing = {
  xs:  4,
  sm:  8,
  md:  16,
  lg:  24,
  xl:  32,
  xxl: 48,
  '3xl': 64,
} as const;

// ─── Border radius ────────────────────────────────────────────────────────────

export const radius = {
  xs:   4,
  sm:   8,
  md:   12,
  lg:   16,
  xl:   20,
  '2xl':24,
  full: 9999,
} as const;

// ─── Type scale ───────────────────────────────────────────────────────────────
// Slightly larger than web — thumb-friendly tap targets, outdoor legibility

export const fontSize = {
  xs:   11,
  sm:   13,
  base: 15,
  md:   17,
  lg:   20,
  xl:   24,
  '2xl':28,
  xxl:  28,   // dot-access alias for '2xl' — several screens use fontSize.xxl
  '3xl':34,
} as const;

export const lineHeight = {
  tight:  1.2,
  normal: 1.45,
  relaxed:1.65,
} as const;

export const fontWeight = {
  regular:   '400' as const,
  medium:    '500' as const,
  semibold:  '600' as const,
  bold:      '700' as const,
  extrabold: '800' as const,
  black:     '900' as const,
};

// ─── Shadows ─────────────────────────────────────────────────────────────────
// ─── Elevation ────────────────────────────────────────────────────────────────
//
// Two mechanisms, because they work on opposite surfaces (plan 0.6):
//
//   LIGHT theme — a cast shadow. Something above a white page occludes light.
//   DARK  theme — a lighter SURFACE. A black shadow on a #0E132F background is
//                 the background; it contributes nothing. Physical light models
//                 break down on dark UI, so material that is "closer" is
//                 lighter instead.
//
// `shadow` below is the light-theme ladder. `elevate(level, colors)` picks the
// right mechanism for the active theme, and is what components should call —
// reaching for `shadow.md` directly is correct only if you know the surface is
// light.

export const shadow = {
  sm: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 2,
  },
  md: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.10,
    shadowRadius: 12,
    elevation: 5,
  },
  lg: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.14,
    shadowRadius: 20,
    elevation: 10,
  },
  // Coloured glow — pass shadowColor separately.
  glow: {
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.30,
    shadowRadius: 12,
    elevation: 8,
  },
} as const;

export type ElevationLevel = 0 | 1 | 2 | 3;

/**
 * Elevation for the ACTIVE theme.
 *
 *   0  flush with the page      1  card        2  raised / menu      3  modal
 *
 * Returns a style object to spread. On light surfaces that is a cast shadow;
 * on dark surfaces it is a lighter background plus a hairline border, because
 * a shadow the colour of the background is not an effect.
 *
 *   <View style={[s.card, elevate(1, c, isDark)]} />
 *
 * `isDark` is passed rather than inferred so this stays a pure function — the
 * caller already has it from useColors()/useTheme().
 */
export function elevate(
  level: ElevationLevel,
  colors: { card: string; surfaceElevated: string; border: string; borderStrong: string },
  isDark: boolean,
) {
  if (level === 0) return {};

  if (isDark) {
    // Lightness carries the depth. The steps are deliberately small (~1.06:1
    // between rungs): elevation should read as the same material lifted, not
    // as a different component.
    return {
      backgroundColor: level >= 2 ? colors.surfaceElevated : colors.card,
      borderWidth: 1,
      borderColor: level >= 3 ? colors.borderStrong : colors.border,
    };
  }

  return level === 1 ? shadow.sm : level === 2 ? shadow.md : shadow.lg;
}

// ─── Animation durations ──────────────────────────────────────────────────────

export const duration = {
  fast:   150,
  normal: 220,
  slow:   350,
} as const;

// ─── Hit slop (WCAG 2.5.5 minimum 44×44pt touch target) ─────────────────────

export const hitSlop = {
  top: 8, bottom: 8, left: 8, right: 8,
} as const;

// ─── Role helpers ─────────────────────────────────────────────────────────────

export type FieldRole = 'driver' | 'walker' | 'trainer' | 'trainee' | 'admin' | 'management' | 'dispatch';

export function getRoleColor(role: FieldRole, colors: ThemeColors): string {
  switch (role) {
    case 'driver':     return colors.driver;
    case 'walker':     return colors.walker;
    case 'trainer':    return colors.trainer;
    case 'trainee':    return colors.trainee;
    default:           return colors.neutral;
  }
}

export function getRoleLight(role: FieldRole, colors: ThemeColors): string {
  switch (role) {
    case 'driver':     return colors.driverLight;
    case 'walker':     return colors.walkerLight;
    case 'trainer':    return colors.trainerLight;
    case 'trainee':    return colors.traineeLight;
    default:           return colors.neutralLight;
  }
}

export const ROLE_LABELS: Record<string, string> = {
  driver:     'Driver',
  walker:     'Walker',
  trainer:    'Trainer',
  trainee:    'Trainee',
  admin:      'Admin',
  management: 'Management',
  dispatch:   'Dispatch',
};
