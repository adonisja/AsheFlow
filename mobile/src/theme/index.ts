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

export type ThemeColors = {
  // Surfaces
  background:       string;
  surface:          string;
  surfaceMuted:     string;
  surfaceElevated:  string;
  card:             string;

  // Text
  foreground:       string;
  mutedForeground:  string;
  subtleForeground: string;

  // Brand
  primary:          string;
  primaryLight:     string;
  primaryForeground:string;

  // Accent
  gold:             string;
  goldLight:        string;

  // Semantic
  success:          string;
  successLight:     string;
  warning:          string;
  warningLight:     string;
  danger:           string;
  dangerLight:      string;
  info:             string;
  infoLight:        string;

  // Role palette
  driver:           string;
  driverLight:      string;
  walker:           string;
  walkerLight:      string;
  trainer:          string;
  trainerLight:     string;
  trainee:          string;
  traineeLight:     string;
  neutral:          string;
  neutralLight:     string;

  // Structure
  border:           string;
  borderStrong:     string;
  ring:             string;

  // Misc
  tabBar:           string;
  tabBarBorder:     string;
  skeleton:         string;
  skeletonShimmer:  string;
};

export const lightColors: ThemeColors = {
  background:         palette.gray50,
  surface:            palette.white,
  surfaceMuted:       palette.gray100,
  surfaceElevated:    palette.white,
  card:               palette.white,

  foreground:         palette.gray900,
  mutedForeground:    palette.gray500,
  subtleForeground:   palette.gray400,

  primary:            palette.indigo500,
  primaryLight:       palette.indigo100,
  primaryForeground:  palette.white,

  gold:               palette.amber500,
  goldLight:          palette.amber100,

  success:            palette.green500,
  successLight:       palette.green100,
  warning:            palette.orange500,
  warningLight:       palette.orange100,
  danger:             palette.red500,
  dangerLight:        palette.red100,
  info:               palette.cyan500,
  infoLight:          palette.cyan100,

  driver:             palette.slate500,
  driverLight:        palette.slate100,
  walker:             palette.teal500,
  walkerLight:        palette.teal100,
  trainer:            palette.amber500,
  trainerLight:       palette.amber100,
  trainee:            palette.cyan500,
  traineeLight:       palette.cyan100,
  neutral:            palette.neutral500,
  neutralLight:       palette.neutral100,

  border:             palette.gray200,
  borderStrong:       '#CBD5E1',
  ring:               palette.indigo500,

  tabBar:             palette.white,
  tabBarBorder:       palette.gray200,
  skeleton:           palette.gray100,
  skeletonShimmer:    'rgba(255,255,255,0.7)',
};

export const darkColors: ThemeColors = {
  background:         palette.dark50,
  surface:            palette.dark100,
  surfaceMuted:       palette.dark200,
  surfaceElevated:    palette.dark300,
  card:               palette.dark100,

  foreground:         '#EDF0F8',
  mutedForeground:    '#8892B0',
  subtleForeground:   '#5A6480',

  primary:            palette.indigo400,
  primaryLight:       palette.indigo900,
  primaryForeground:  palette.white,

  gold:               palette.amber400,
  goldLight:          palette.amber900,

  success:            palette.green400,
  successLight:       palette.green900,
  warning:            palette.orange400,
  warningLight:       palette.orange900,
  danger:             palette.red400,
  dangerLight:        palette.red900,
  info:               palette.cyan400,
  infoLight:          palette.cyan900,

  driver:             palette.slate400,
  driverLight:        palette.slate900,
  walker:             palette.teal400,
  walkerLight:        palette.teal900,
  trainer:            palette.amber400,
  trainerLight:       palette.amber900,
  trainee:            palette.cyan400,
  traineeLight:       palette.cyan900,
  neutral:            palette.neutral400,
  neutralLight:       palette.neutral900,

  border:             palette.dark400,
  borderStrong:       palette.dark500,
  ring:               palette.indigo400,

  tabBar:             palette.dark100,
  tabBarBorder:       palette.dark400,
  skeleton:           palette.dark200,
  skeletonShimmer:    'rgba(255,255,255,0.04)',
};

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
// Elevation levels for React Native shadow props

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
  // Colored glow — pass shadowColor separately
  glow: {
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.30,
    shadowRadius: 12,
    elevation: 8,
  },
} as const;

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
