// AsheFlow mobile design tokens
// Philosophy: same token names as the web system (index.css) for mental-model parity,
// but values are shifted vibrant + high-contrast for outdoor, sunlight-readable use
// by field staff on Android/iOS. The web palette is muted/professional for office/exec
// users — this palette is energetic and clear.

// ─── Raw palette ─────────────────────────────────────────────────────────────

export const palette = {
  // Brand — electric indigo (web is 225 70% 55%; mobile is lifted for saturation)
  indigo500:  '#4F6BF4',   // primary action, interactive
  indigo400:  '#7B8FF7',   // primary lifted (dark mode)
  indigo100:  '#E8ECFE',   // primary tint fill (light)
  indigo900:  '#1A2060',   // primary deep (dark mode tint fill)

  // Accent — vivid amber (web gold is muted #D4A832; mobile is punchy)
  amber500:   '#F59E0B',   // trainer role, gold accent
  amber400:   '#FBB830',   // amber lifted (dark mode)
  amber100:   '#FEF3C7',   // amber tint (light)
  amber900:   '#3D2500',   // amber tint (dark)

  // Role — teal (walker)
  teal500:    '#0EA5A0',   // more saturated than web #0FA870
  teal400:    '#2DD4BF',   // teal lifted (dark)
  teal100:    '#CCFBF1',   // tint (light)
  teal900:    '#062E2C',   // tint (dark)

  // Role — slate (driver) — brighter than web's desaturated slate
  slate500:   '#3B82F6',   // vibrant blue-slate
  slate400:   '#60A5FA',
  slate100:   '#DBEAFE',
  slate900:   '#1E2D50',

  // Role — neutral (admin/management)
  neutral500: '#6B7280',
  neutral400: '#9CA3AF',
  neutral100: '#F3F4F6',
  neutral900: '#1F2937',

  // Semantic — calibrated for small-screen readability in sunlight
  green500:   '#10B981',   // success (confirmed)
  green400:   '#34D399',
  green100:   '#D1FAE5',
  green900:   '#064E3B',

  orange500:  '#F97316',   // warning (pending) — distinct from amber
  orange400:  '#FB923C',
  orange100:  '#FFEDD5',
  orange900:  '#431407',

  red500:     '#EF4444',   // danger
  red400:     '#F87171',
  red100:     '#FEE2E2',
  red900:     '#450A0A',

  cyan500:    '#06B6D4',   // info (assigned)
  cyan400:    '#22D3EE',
  cyan100:    '#CFFAFE',
  cyan900:    '#0C2A3A',

  // Surfaces — light (Frost White, same family as web)
  gray50:     '#F8FAFC',
  gray100:    '#F1F5F9',
  gray200:    '#E2E8F0',
  gray400:    '#94A3B8',
  gray500:    '#64748B',
  gray700:    '#334155',
  gray900:    '#0F172A',

  // Surfaces — dark (Deep Space — darker/richer than web charcoal)
  dark50:     '#0B0D14',
  dark100:    '#111320',
  dark200:    '#181B2E',
  dark300:    '#1F2340',
  dark400:    '#272C4A',
  dark500:    '#343A5C',

  white:      '#FFFFFF',
  black:      '#000000',
};

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
