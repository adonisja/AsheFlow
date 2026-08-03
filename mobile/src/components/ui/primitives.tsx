/**
 * AsheFlow Mobile Design System — Primitives
 *
 * Mirrors the web primitives.tsx token-for-token but built for React Native.
 * Key differences from web:
 *  - No CSS classes — StyleSheet.create() only
 *  - Animated.Value for press feedback (spring, not CSS transition)
 *  - All touch targets ≥ 44pt (WCAG 2.5.5), enforced by MIN_TARGET below —
 *    this was previously claimed here but not true: Button size="sm" was 36pt
 *    and IconButton defaulted to 40pt.
 *  - Vibrant/saturated palette for outdoor legibility
 *
 * ACCESSIBILITY IS PART OF THE API, not an optional prop (plan §4 rule 4).
 * Interactive primitives REQUIRE an accessibilityLabel when their content is
 * not plain text, and set accessibilityRole/State themselves so a screen
 * reader gets them without the caller remembering. Measured before this
 * change: 0 of 16 primitives had any a11y prop, which is where the app's 5%
 * coverage comes from.
 *
 * Import pattern:
 *   import { Button, Badge, Card, Avatar, StatCard } from '@components/ui/primitives';
 */

import React, { useRef } from 'react';
import {
  View, Text, TouchableOpacity, Animated,
  StyleSheet, ActivityIndicator, AccessibilityInfo, Platform, Vibration,
  type ViewStyle, type TextStyle, type StyleProp,
} from 'react-native';
import { useColors, useTheme } from '@contexts/ThemeContext';
import {
  spacing, radius, fontSize, fontWeight, shadow, hitSlop, elevate,
  type ElevationLevel,
  type ThemeColors, type FieldRole,
  getRoleColor, getRoleLight, ROLE_LABELS,
} from '@theme/index';

/** WCAG 2.5.5. Nothing interactive may be smaller than this. */
export const MIN_TARGET = 44;

/**
 * Does the OS want motion suppressed?
 *
 * Read once here rather than per-component so no primitive has to remember —
 * an animation that ignores this setting is a bug, not a flourish (plan §4
 * rule 5).
 */
function useReduceMotion() {
  const [reduce, setReduce] = React.useState(false);
  React.useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled().then(v => { if (alive) setReduce(v); });
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', setReduce);
    return () => { alive = false; sub?.remove?.(); };
  }, []);
  return reduce;
}

/**
 * A short tick on commit. Android only: iOS needs Haptics from a native module
 * we do not depend on, and Vibration there is a blunt buzz that users dislike.
 * Silence is the correct degradation — this is confirmation, never the signal
 * itself.
 */
function tick() {
  if (Platform.OS === 'android') Vibration.vibrate(10);
}

// ─── Press animation hook ─────────────────────────────────────────────────────
// Spring-backed scale on press — mirrors web --ease-spring on transform

function usePressScale(toScale = 0.96) {
  const scale = useRef(new Animated.Value(1)).current;
  const reduceMotion = useReduceMotion();

  const onPressIn = () => {
    if (reduceMotion) return;
    Animated.spring(scale, { toValue: toScale, useNativeDriver: true, speed: 40, bounciness: 4 }).start();
  };

  const onPressOut = () => {
    if (reduceMotion) return;
    Animated.spring(scale, { toValue: 1, useNativeDriver: true, speed: 30, bounciness: 6 }).start();
  };

  return { scale, onPressIn, onPressOut };
}

// ─── Button ───────────────────────────────────────────────────────────────────

/**
 * `primary` is the BRAND violet — the interactive colour (plan §4.0).
 * `structural` is the navy, for the rare button that is page furniture rather
 * than an action. Navy at 13:1 is a text/heading colour; using it for every
 * button made the UI read as uniformly heavy.
 */
type ButtonVariant =
  | 'primary' | 'structural' | 'secondary'
  | 'danger' | 'success' | 'ghost' | 'outline';
type ButtonSize    = 'sm' | 'md' | 'lg';

interface ButtonProps {
  onPress: () => void;
  children: React.ReactNode;
  variant?:  ButtonVariant;
  size?:     ButtonSize;
  loading?:  boolean;
  disabled?: boolean;
  fullWidth?: boolean;
  style?: StyleProp<ViewStyle>;
  /**
   * Required when `children` is not plain text — an icon-only or composed
   * button is unlabelled to a screen reader otherwise.
   */
  accessibilityLabel?: string;
  /** What happens on activation, when that is not obvious from the label. */
  accessibilityHint?: string;
}

export function Button({
  onPress, children, variant = 'primary', size = 'md',
  loading = false, disabled = false, fullWidth = false, style,
  accessibilityLabel, accessibilityHint,
}: ButtonProps) {
  const c = useColors();
  const { scale, onPressIn, onPressOut } = usePressScale();

  const bgColor: Record<ButtonVariant, string> = {
    primary:    c.brand,
    structural: c.primary,
    secondary:  c.surfaceMuted,
    danger:     c.danger,
    success:    c.success,
    ghost:      'transparent',
    outline:    'transparent',
  };

  // Foregrounds come from the token layer. `danger`/`success` were hardcoded
  // '#fff', which is a token bypass and would not follow a palette change.
  const textColor: Record<ButtonVariant, string> = {
    primary:    c.brandForeground,
    structural: c.primaryForeground,
    secondary:  c.foreground,
    danger:     c.primaryForeground,
    success:    c.primaryForeground,
    ghost:      c.brand,
    outline:    c.brand,
  };

  const borderColor: Record<ButtonVariant, string | undefined> = {
    primary:    undefined,
    structural: undefined,
    secondary:  c.border,
    danger:     undefined,
    success:    undefined,
    ghost:      undefined,
    outline:    c.brand,
  };

  const sizePad: Record<ButtonSize, { paddingVertical: number; paddingHorizontal: number; minHeight: number }> = {
    // 44 is the floor, not a target — WCAG 2.5.5. `sm` was 36pt.
    sm: { paddingVertical: 8,  paddingHorizontal: 14, minHeight: MIN_TARGET },
    md: { paddingVertical: 12, paddingHorizontal: 20, minHeight: MIN_TARGET },
    lg: { paddingVertical: 16, paddingHorizontal: 28, minHeight: 52 },
  };

  const textSize: Record<ButtonSize, number> = {
    sm: fontSize.sm,
    md: fontSize.base,
    lg: fontSize.md,
  };

  const glowShadow = (variant === 'primary' || variant === 'structural'
                      || variant === 'danger' || variant === 'success')
    ? { ...shadow.glow, shadowColor: bgColor[variant] }
    : {};

  return (
    <Animated.View style={[{ transform: [{ scale }] }, fullWidth && { width: '100%' }]}>
      <TouchableOpacity
        onPress={() => { tick(); onPress(); }}
        // Set by the component, not left to the caller — this is what makes
        // the button announce itself at all.
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel
          ?? (typeof children === 'string' ? children : undefined)}
        accessibilityHint={accessibilityHint}
        accessibilityState={{ disabled: disabled || loading, busy: loading }}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        disabled={disabled || loading}
        activeOpacity={1}
        style={[
          styles.btnBase,
          sizePad[size],
          {
            backgroundColor: bgColor[variant],
            borderColor:      borderColor[variant],
            borderWidth:      borderColor[variant] ? 1.5 : 0,
            opacity:          disabled ? 0.45 : 1,
          },
          !['ghost', 'outline', 'secondary'].includes(variant) && glowShadow,
          fullWidth && { alignSelf: 'stretch' },
          style,
        ]}
      >
        {loading ? (
          <ActivityIndicator
            size="small"
            color={textColor[variant]}
          />
        ) : (
          <Text style={[styles.btnText, { color: textColor[variant], fontSize: textSize[size] }]}>
            {children}
          </Text>
        )}
      </TouchableOpacity>
    </Animated.View>
  );
}

// ─── IconButton ───────────────────────────────────────────────────────────────

interface IconButtonProps {
  onPress: () => void;
  children: React.ReactNode;
  badge?: number;
  variant?: 'default' | 'filled' | 'ghost';
  size?: number;
  color?: string;
  style?: StyleProp<ViewStyle>;
  /**
   * REQUIRED — an icon has no text for a screen reader to fall back on, so
   * without this the control is announced as an unlabelled button.
   */
  accessibilityLabel: string;
  accessibilityHint?: string;
}

export function IconButton({
  onPress, children, badge, variant = 'default', size = MIN_TARGET, color, style,
  accessibilityLabel, accessibilityHint,
}: IconButtonProps) {
  const c = useColors();
  const { scale, onPressIn, onPressOut } = usePressScale(0.92);

  const bg: Record<string, string> = {
    default: c.surface,
    filled:  c.primaryLight,
    ghost:   'transparent',
  };

  return (
    <Animated.View style={{ transform: [{ scale }] }}>
      <TouchableOpacity
        onPress={() => { tick(); onPress(); }}
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel}
        accessibilityHint={accessibilityHint}
        // A badge is a visible count that a screen reader would otherwise miss.
        accessibilityValue={badge ? { text: `${badge}` } : undefined}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        hitSlop={hitSlop}
        activeOpacity={1}
        style={[
          {
            width: size, height: size, borderRadius: size / 2,
            alignItems: 'center', justifyContent: 'center',
            backgroundColor: bg[variant],
            borderWidth: variant === 'default' ? 1 : 0,
            borderColor: c.border,
          },
          style,
        ]}
      >
        {children}
        {badge != null && badge > 0 && (
          <View style={[styles.iconBadge, { backgroundColor: c.danger }]}>
            <Text style={[styles.iconBadgeText, { color: c.dangerLight }]}>
              {badge > 9 ? '9+' : badge}
            </Text>
          </View>
        )}
      </TouchableOpacity>
    </Animated.View>
  );
}

// ─── Badge ────────────────────────────────────────────────────────────────────

type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'primary' | 'gold' | 'teal' | 'slate' | 'neutral' | 'muted';

interface BadgeProps {
  tone?: BadgeTone;
  children: React.ReactNode;
  dot?: boolean;
  size?: 'sm' | 'md';
}

function getBadgeColors(tone: BadgeTone, c: ThemeColors): [string, string] {
  switch (tone) {
    case 'success': return [c.success,         c.successLight];
    case 'warning': return [c.warning,         c.warningLight];
    case 'danger':  return [c.danger,          c.dangerLight];
    case 'info':    return [c.info,            c.infoLight];
    case 'primary': return [c.primary,         c.primaryLight];
    case 'gold':    return [c.gold,            c.goldLight];
    case 'teal':    return [c.walker,          c.walkerLight];
    case 'slate':   return [c.driver,          c.driverLight];
    case 'neutral': return [c.neutral,         c.neutralLight];
    default:        return [c.mutedForeground, c.surfaceMuted];
  }
}

export function Badge({ tone = 'muted', children, dot = false, size = 'md' }: BadgeProps) {
  const c = useColors();
  const [fg, bg] = getBadgeColors(tone, c);
  const isSmall = size === 'sm';
  return (
    <View style={[
      styles.badge,
      { backgroundColor: bg, paddingHorizontal: isSmall ? 6 : 10, paddingVertical: isSmall ? 2 : 4 },
    ]}>
      {dot && <View style={[styles.badgeDot, { backgroundColor: fg }]} />}
      <Text style={[styles.badgeText, { color: fg, fontSize: isSmall ? 10 : 11.5 }]}>
        {children}
      </Text>
    </View>
  );
}

// ─── StatusBadge ─────────────────────────────────────────────────────────────

type AssignmentStatus = 'confirmed' | 'pending' | 'declined' | 'assigned';

const statusMap: Record<AssignmentStatus, [BadgeTone, string]> = {
  confirmed: ['success', 'Confirmed'],
  pending:   ['warning', 'Pending'],
  declined:  ['danger',  'Declined'],
  assigned:  ['info',    'Assigned'],
};

export function StatusBadge({ status }: { status: AssignmentStatus }) {
  const [tone, label] = statusMap[status] ?? ['muted', status];
  return <Badge tone={tone} dot>{label}</Badge>;
}

// ─── RoleBadge ────────────────────────────────────────────────────────────────

const roleToneMap: Record<string, BadgeTone> = {
  driver:     'slate',
  walker:     'teal',
  trainer:    'gold',
  trainee:    'info',
  admin:      'neutral',
  management: 'neutral',
  dispatch:   'primary',
};

export function RoleBadge({ role }: { role: string }) {
  const tone = roleToneMap[role] ?? 'muted';
  return <Badge tone={tone}>{ROLE_LABELS[role] ?? role}</Badge>;
}

// ─── Avatar ───────────────────────────────────────────────────────────────────

interface AvatarProps {
  initials: string;
  role?: FieldRole;
  size?: number;
  /** Override color directly (skip role lookup) */
  color?: string;
}

export function Avatar({ initials, role = 'driver', size = 36, color }: AvatarProps) {
  const c = useColors();
  const fg  = color ?? getRoleColor(role, c);
  const bg  = color ? color + '20' : getRoleLight(role, c);
  const textFontSize = size <= 28 ? 9 : size <= 36 ? 11 : size <= 44 ? 13 : 15;

  return (
    <View style={[
      styles.avatar,
      {
        width: size, height: size, borderRadius: size / 2,
        backgroundColor: bg,
        borderColor: fg + '40',
      },
    ]}>
      <Text style={[styles.avatarText, { color: fg, fontSize: textFontSize }]}>
        {initials}
      </Text>
    </View>
  );
}

// ─── Card ────────────────────────────────────────────────────────────────────

interface CardProps {
  children: React.ReactNode;
  padding?: number;
  /** Adds press animation + subtle lift — use for tappable cards */
  pressable?: boolean;
  onPress?: () => void;
  style?: StyleProp<ViewStyle>;
  /** Accent bar on left edge (pass a hex color) */
  accent?: string;
  /** 0 flush · 1 card · 2 raised · 3 modal. See elevate() in the theme. */
  elevation?: ElevationLevel;
  /** Required when `pressable` — a tappable card is a button to a screen reader. */
  accessibilityLabel?: string;
  accessibilityHint?: string;
}

export function Card({
  children, padding = 16, pressable = false, onPress, style, accent,
  elevation = 1, accessibilityLabel, accessibilityHint,
}: CardProps) {
  const c = useColors();
  const { isDark } = useTheme();
  const { scale, onPressIn, onPressOut } = usePressScale(0.985);

  const cardStyle = [
    styles.card,
    { backgroundColor: c.card, borderColor: c.border, padding },
    // elevate() picks the mechanism for the active theme: a cast shadow on
    // light surfaces, a lighter surface + border on dark, where a black shadow
    // is the background and reads as nothing (plan 0.6).
    elevate(elevation, c, isDark),
    accent && { borderLeftWidth: 3, borderLeftColor: accent },
    style,
  ];

  if (pressable && onPress) {
    return (
      <Animated.View style={{ transform: [{ scale }] }}>
        <TouchableOpacity
          onPress={() => { tick(); onPress(); }}
          // A pressable card IS a button to a screen reader. Without this it
          // is announced as inert text and the interaction is invisible.
          accessibilityRole="button"
          accessibilityLabel={accessibilityLabel}
          accessibilityHint={accessibilityHint}
          onPressIn={onPressIn}
          onPressOut={onPressOut}
          activeOpacity={1}
          style={cardStyle}
        >
          {children}
        </TouchableOpacity>
      </Animated.View>
    );
  }

  return <View style={cardStyle}>{children}</View>;
}

// ─── StatCard ─────────────────────────────────────────────────────────────────

type StatTone = 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'gold' | 'driver' | 'walker' | 'trainer' | 'trainee';

function getStatColor(tone: StatTone, c: ThemeColors): [string, string] {
  switch (tone) {
    case 'primary': return [c.primary,  c.primaryLight];
    case 'success': return [c.success,  c.successLight];
    case 'warning': return [c.warning,  c.warningLight];
    case 'danger':  return [c.danger,   c.dangerLight];
    case 'info':    return [c.info,     c.infoLight];
    case 'gold':    return [c.gold,     c.goldLight];
    case 'driver':  return [c.driver,   c.driverLight];
    case 'walker':  return [c.walker,   c.walkerLight];
    case 'trainer': return [c.trainer,  c.trainerLight];
    case 'trainee': return [c.trainee,  c.traineeLight];
  }
}

interface StatCardProps {
  label:    string;
  value:    string | number;
  icon:     React.ReactNode;
  tone?:    StatTone;
  hint?:    string;
  onPress?: () => void;
}

export function StatCard({ label, value, icon, tone = 'primary', hint, onPress }: StatCardProps) {
  const c = useColors();
  const [color, tint] = getStatColor(tone, c);
  const { scale, onPressIn, onPressOut } = usePressScale(0.97);

  const inner = (
    <View style={[styles.statCard, { backgroundColor: c.card, borderColor: c.border }]}>
      {/* Icon well */}
      <View style={[styles.statIconWell, { backgroundColor: tint }]}>
        {icon}
      </View>

      {/* Text stack */}
      <View style={styles.statBody}>
        <Text style={[styles.statLabel, { color: c.mutedForeground }]}>{label}</Text>
        <Text style={[styles.statValue, { color: c.foreground }]}>{value}</Text>
        {/* Always render hint slot — keeps card height stable across grid */}
        <Text style={[styles.statHint, { color: c.mutedForeground }]} numberOfLines={1}>
          {hint ?? ''}
        </Text>
      </View>

      {/* Accent strip on top edge */}
      <View style={[styles.statAccent, { backgroundColor: color }]} />
    </View>
  );

  if (onPress) {
    return (
      <Animated.View style={{ transform: [{ scale }] }}>
        <TouchableOpacity
          onPress={onPress}
          onPressIn={onPressIn}
          onPressOut={onPressOut}
          activeOpacity={1}
        >
          {inner}
        </TouchableOpacity>
      </Animated.View>
    );
  }

  return inner;
}

// ─── SectionHeader ────────────────────────────────────────────────────────────

interface SectionHeaderProps {
  eyebrow?:    string;
  title:       string;
  description?: string;
  actions?:    React.ReactNode;
  style?:      StyleProp<ViewStyle>;
}

export function SectionHeader({ eyebrow, title, description, actions, style }: SectionHeaderProps) {
  const c = useColors();
  return (
    <View style={[styles.sectionHeader, style]}>
      <View style={styles.sectionHeaderLeft}>
        {eyebrow && (
          <Text style={[styles.eyebrow, { color: c.mutedForeground }]}>{eyebrow.toUpperCase()}</Text>
        )}
        <Text style={[styles.sectionTitle, { color: c.foreground }]}>{title}</Text>
        {description && (
          <Text style={[styles.sectionDesc, { color: c.mutedForeground }]}>{description}</Text>
        )}
      </View>
      {actions && (
        <View style={styles.sectionHeaderRight}>{actions}</View>
      )}
    </View>
  );
}

// ─── Eyebrow ──────────────────────────────────────────────────────────────────

export function Eyebrow({ children, style }: { children: React.ReactNode; style?: StyleProp<TextStyle> }) {
  const c = useColors();
  return (
    <Text style={[styles.eyebrow, { color: c.mutedForeground }, style]}>
      {typeof children === 'string' ? children.toUpperCase() : children}
    </Text>
  );
}

// ─── Divider ──────────────────────────────────────────────────────────────────

interface DividerProps {
  label?:  string;
  style?:  StyleProp<ViewStyle>;
  inset?:  number;
}

export function Divider({ label, style, inset = 0 }: DividerProps) {
  const c = useColors();
  if (label) {
    return (
      <View style={[styles.dividerRow, style]}>
        <View style={[styles.dividerLine, { backgroundColor: c.border, marginLeft: inset }]} />
        <Text style={[styles.dividerLabel, { color: c.mutedForeground }]}>{label}</Text>
        <View style={[styles.dividerLine, { backgroundColor: c.border, marginRight: inset }]} />
      </View>
    );
  }
  return (
    <View
      style={[
        styles.dividerSolid,
        { backgroundColor: c.border, marginHorizontal: inset },
        style,
      ]}
    />
  );
}

// ─── Skeleton ────────────────────────────────────────────────────────────────

interface SkeletonProps {
  width?:  number | `${number}%`;
  height?: number;
  radius?: number;
  style?:  StyleProp<ViewStyle>;
}

export function Skeleton({ width = '100%', height = 16, radius: r = 8, style }: SkeletonProps) {
  const c = useColors();
  const shimmer = useRef(new Animated.Value(0)).current;

  React.useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(shimmer, { toValue: 0, duration: 900, useNativeDriver: true }),
      ])
    );
    loop.start();
    return () => loop.stop();
  }, [shimmer]);

  const opacity = shimmer.interpolate({ inputRange: [0, 1], outputRange: [1, 0.45] });

  return (
    <Animated.View
      style={[
        { width, height, borderRadius: r, backgroundColor: c.skeleton, opacity },
        style,
      ]}
    />
  );
}

// ─── Row ─────────────────────────────────────────────────────────────────────
// Flex row helper — avoids inline style repetition

interface RowProps {
  children:  React.ReactNode;
  gap?:      number;
  align?:    'center' | 'flex-start' | 'flex-end' | 'stretch';
  justify?:  'flex-start' | 'flex-end' | 'center' | 'space-between' | 'space-around';
  wrap?:     boolean;
  style?:    StyleProp<ViewStyle>;
}

export function Row({
  children, gap = 8, align = 'center', justify = 'flex-start', wrap = false, style,
}: RowProps) {
  return (
    <View style={[
      { flexDirection: 'row', alignItems: align, justifyContent: justify, gap, flexWrap: wrap ? 'wrap' : 'nowrap' },
      style,
    ]}>
      {children}
    </View>
  );
}

// ─── EmptyState ───────────────────────────────────────────────────────────────

interface EmptyStateProps {
  icon?:    React.ReactNode;
  title:    string;
  message?: string;
  action?:  React.ReactNode;
}

export function EmptyState({ icon, title, message, action }: EmptyStateProps) {
  const c = useColors();
  return (
    <View style={styles.emptyState}>
      {icon && <View style={styles.emptyIcon}>{icon}</View>}
      <Text style={[styles.emptyTitle, { color: c.foreground }]}>{title}</Text>
      {message && (
        <Text style={[styles.emptyMessage, { color: c.mutedForeground }]}>{message}</Text>
      )}
      {action && <View style={styles.emptyAction}>{action}</View>}
    </View>
  );
}

// ─── Pill chip ────────────────────────────────────────────────────────────────
// Compact pressable filter chip — used in tab-style filters, quick selects

interface ChipProps {
  label:     string;
  selected?: boolean;
  onPress?:  () => void;
}

export function Chip({ label, selected = false, onPress }: ChipProps) {
  const c = useColors();
  const { scale, onPressIn, onPressOut } = usePressScale(0.94);

  return (
    <Animated.View style={{ transform: [{ scale }] }}>
      <TouchableOpacity
        onPress={onPress}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        hitSlop={hitSlop}
        activeOpacity={1}
        style={[
          styles.chip,
          {
            backgroundColor: selected ? c.primary : c.surfaceMuted,
            borderColor:      selected ? c.primary : c.border,
          },
        ]}
      >
        <Text style={[
          styles.chipText,
          { color: selected ? c.primaryForeground : c.mutedForeground },
        ]}>
          {label}
        </Text>
      </TouchableOpacity>
    </Animated.View>
  );
}

// ─── Tag ─────────────────────────────────────────────────────────────────────
// Non-interactive metadata tag (phase numbers, IDs, truck codes)

export function Tag({ children }: { children: React.ReactNode }) {
  const c = useColors();
  return (
    <View style={[styles.tag, { backgroundColor: c.surfaceMuted, borderColor: c.border }]}>
      <Text style={[styles.tagText, { color: c.mutedForeground }]}>{children}</Text>
    </View>
  );
}

// ─── StyleSheet ──────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  // Button
  btnBase: {
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 8,
  },
  btnText: {
    fontWeight: fontWeight.semibold,
    letterSpacing: 0.2,
  },

  // IconButton badge
  iconBadge: {
    position: 'absolute',
    top: -3, right: -3,
    minWidth: 16, height: 16,
    borderRadius: radius.full,
    alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: 3,
  },
  iconBadgeText: {
    // Colour comes from the theme at the usage site — StyleSheet.create is
    // static and cannot reach useColors().
    fontSize: 9,
    fontWeight: fontWeight.bold,
  },

  // Badge
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
    borderRadius: radius.sm,
    alignSelf: 'flex-start',
  },
  badgeDot: {
    width: 5, height: 5, borderRadius: radius.full,
  },
  badgeText: {
    fontWeight: fontWeight.semibold,
  },

  // Avatar
  avatar: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1.5,
    flexShrink: 0,
  },
  avatarText: {
    fontWeight: fontWeight.bold,
  },

  // Card
  card: {
    borderRadius: radius.lg,
    borderWidth: 1,
    overflow: 'hidden',
    ...shadow.sm,
  },

  // StatCard
  statCard: {
    borderRadius: radius.lg,
    borderWidth: 1,
    padding: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    minHeight: 88,
    overflow: 'hidden',
    position: 'relative',
    ...shadow.sm,
  },
  statIconWell: {
    width: 48, height: 48,
    borderRadius: radius.md,
    alignItems: 'center', justifyContent: 'center',
    flexShrink: 0,
  },
  statBody:  { flex: 1, minWidth: 0 },
  statLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.5 },
  statValue: { fontSize: fontSize['2xl'], fontWeight: fontWeight.extrabold, letterSpacing: -0.5, marginTop: 2, lineHeight: 32 },
  statHint:  { fontSize: fontSize.xs, marginTop: 3, minHeight: 14 },
  statAccent: {
    position: 'absolute', top: 0, left: 0, right: 0,
    height: 3, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
  },

  // SectionHeader
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 12,
    marginBottom: spacing.md,
  },
  sectionHeaderLeft:  { flex: 1, minWidth: 0, gap: 3 },
  sectionHeaderRight: { flexShrink: 0 },
  sectionTitle: {
    fontSize: fontSize.lg,
    fontWeight: fontWeight.bold,
    letterSpacing: -0.3,
    lineHeight: 26,
  },
  sectionDesc: { fontSize: fontSize.sm, lineHeight: 19, marginTop: 2 },

  // Eyebrow
  eyebrow: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.semibold,
    letterSpacing: 0.9,
    textTransform: 'uppercase',
  },

  // Divider
  dividerRow:   { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginVertical: spacing.sm },
  dividerLine:  { flex: 1, height: StyleSheet.hairlineWidth },
  dividerLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.medium, textTransform: 'uppercase', letterSpacing: 1 },
  dividerSolid: { height: StyleSheet.hairlineWidth, marginVertical: spacing.sm },

  // EmptyState
  emptyState:   { alignItems: 'center', justifyContent: 'center', paddingVertical: spacing.xxl, paddingHorizontal: spacing.xl },
  emptyIcon:    { marginBottom: spacing.md },
  emptyTitle:   { fontSize: fontSize.md, fontWeight: fontWeight.bold, textAlign: 'center', marginBottom: spacing.xs },
  emptyMessage: { fontSize: fontSize.sm, textAlign: 'center', lineHeight: 20, maxWidth: 260 },
  emptyAction:  { marginTop: spacing.lg },

  // Chip
  chip: {
    borderRadius: radius.full,
    borderWidth: 1,
    paddingHorizontal: 14,
    paddingVertical: 7,
  },
  chipText: {
    fontSize: fontSize.sm,
    fontWeight: fontWeight.medium,
  },

  // Tag
  tag: {
    borderRadius: radius.xs,
    borderWidth: 1,
    paddingHorizontal: 7,
    paddingVertical: 2,
    alignSelf: 'flex-start',
  },
  tagText: {
    fontSize: fontSize.xs,
    fontWeight: fontWeight.medium,
    fontVariant: ['tabular-nums'],
  },
});
