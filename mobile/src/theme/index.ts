// AsheFlow mobile design tokens — mirrors the web design system (index.css)
// Light and dark palettes share the same token names.

export const palette = {
  // Brand — Indigo
  primary: '#5B4FE8',
  primaryLight: '#EEF0FF',
  primaryGlow: '#7B6FF5',

  // Accent — Soft Gold
  gold: '#D4A832',
  goldDark: '#7A5A08',

  // Surfaces — light
  backgroundLight: '#F7F8FC',
  surfaceLight: '#FFFFFF',
  surfaceMutedLight: '#F0F2F8',
  cardLight: '#FFFFFF',

  // Surfaces — dark
  backgroundDark: '#0D0F18',
  surfaceDark: '#141620',
  surfaceMutedDark: '#1B1E2B',
  cardDark: '#141620',

  // Foreground
  foregroundLight: '#111827',
  foregroundDark: '#EDF0F7',
  mutedForegroundLight: '#6B7280',
  mutedForegroundDark: '#8A91A8',

  // Borders
  borderLight: '#E2E6EF',
  borderDark: '#232639',

  // Semantic
  success: '#0FA870',
  successDark: '#18C985',
  warning: '#E8820C',
  warningDark: '#F0A030',
  danger: '#DC2626',
  dangerDark: '#EF5252',
  info: '#0EA5D8',
};

export type ThemeColors = {
  background: string;
  surface: string;
  surfaceMuted: string;
  card: string;
  foreground: string;
  mutedForeground: string;
  border: string;
  primary: string;
  primaryLight: string;
  gold: string;
  success: string;
  warning: string;
  danger: string;
  info: string;
};

export const lightColors: ThemeColors = {
  background:       palette.backgroundLight,
  surface:          palette.surfaceLight,
  surfaceMuted:     palette.surfaceMutedLight,
  card:             palette.cardLight,
  foreground:       palette.foregroundLight,
  mutedForeground:  palette.mutedForegroundLight,
  border:           palette.borderLight,
  primary:          palette.primary,
  primaryLight:     palette.primaryLight,
  gold:             palette.gold,
  success:          palette.success,
  warning:          palette.warning,
  danger:           palette.danger,
  info:             palette.info,
};

export const darkColors: ThemeColors = {
  background:       palette.backgroundDark,
  surface:          palette.surfaceDark,
  surfaceMuted:     palette.surfaceMutedDark,
  card:             palette.cardDark,
  foreground:       palette.foregroundDark,
  mutedForeground:  palette.mutedForegroundDark,
  border:           palette.borderDark,
  primary:          palette.primaryGlow,
  primaryLight:     '#1E1F35',
  gold:             palette.goldDark,
  success:          palette.successDark,
  warning:          palette.warningDark,
  danger:           palette.dangerDark,
  info:             palette.info,
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
};

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  full: 9999,
};

export const fontSize = {
  xs: 11,
  sm: 13,
  base: 15,
  md: 17,
  lg: 20,
  xl: 24,
  xxl: 30,
};

export const fontWeight = {
  regular: '400' as const,
  medium:  '500' as const,
  semibold:'600' as const,
  bold:    '700' as const,
  extrabold:'800' as const,
};
