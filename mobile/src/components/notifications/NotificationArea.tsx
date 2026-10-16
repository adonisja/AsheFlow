/**
 * The notification area on every screen (ADR-516).
 *
 * Three pieces, all mounted once in MainShell and fed by NotificationsContext:
 *
 *   NotificationTopArea   pinned under the status bar: URGENT cards (ADR-487
 *                         D4a, cannot be scrolled past or bulk-dismissed), then
 *                         one "N need you" row that opens a sheet (D3).
 *   NotificationTickerDock just above the tab bar: the ticker (D4).
 *   ArrivalBanner         a slide-down banner for what just arrived, by tier (D2).
 *
 * Each renders NOTHING when it has nothing to show (owner, D1): no empty strip,
 * no reserved space. That is also why they sit outside the screens: a strip
 * inside a ScrollView is "one swipe from gone" (ADR-381).
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  AccessibilityInfo, Animated, Easing, Modal, Platform, Pressable, ScrollView,
  StyleSheet, Text, Vibration, View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '@contexts/AuthContext';
import { useColors, useTheme } from '@contexts/ThemeContext';
import { useNotifications, type LiveNotification } from '@contexts/NotificationsContext';
import { spacing, radius, fontSize, fontWeight, elevate, type ThemeColors } from '@theme/index';
import { MIN_TARGET, tick } from '@components/ui/primitives';
import { useTabSwitch } from '@navigation/index';
import { resolveActionRoute } from '@navigation/actionRoutes';
import { onPushOpened } from '@api/pushRegistration';
import { useReducedMotionState } from '../../hooks/useReducedMotionState';
import { NotificationTicker } from './NotificationTicker';
import { toneStyle, urgentStyle } from './tone';
import { arrivalOutcome, capUrgent, partitionArea } from './area';
import { formatRelative } from './time';

const INBOX = 'Notifications';
const BANNER_MS = 5000;

/**
 * Open what a notification is about (ADR-519), else the inbox. Exported so the
 * inbox and the area open things the same way.
 *
 *   help_request -> its sheet (there is no tab for one request)
 *   anything else -> the link's route mapped to a tab, with {id, date, kind}
 *                    so a screen that can focus the item does
 *   no link (an older server) -> the type's first registry action, as before
 */
export function useOpenNotification() {
  const { capabilities } = useAuth();
  const { openHelpRequest } = useNotifications();
  const switchTab = useTabSwitch();
  return useCallback((n: Pick<LiveNotification, 'link' | 'actions'>) => {
    const link = n.link;
    if (link?.kind === 'help_request' && link.id) { openHelpRequest(link.id); return; }
    const features = capabilities?.features ?? [];
    let target = link ? resolveActionRoute(link.route.split('?')[0], features) : null;
    if (!target && n.actions?.[0]?.route) target = resolveActionRoute(n.actions[0].route, features);
    const params = link && (link.id || link.date) ? { id: link.id, date: link.date, kind: link.kind } : undefined;
    switchTab(target ?? INBOX, target ? params : undefined);   // never nowhere (ADR-516 D6)
  }, [capabilities, openHelpRequest, switchTab]);
}
const useOpen = useOpenNotification;

/**
 * A tapped system push opens what it is about, exactly as tapping it in the
 * app would (ADR-519 D8). Mounted once, inside the providers. A push from an
 * older server has no `link_route` and opens the inbox.
 */
export function PushTapHandler() {
  const open = useOpenNotification();
  const switchTab = useTabSwitch();
  const { refresh } = useNotifications();
  const { capabilities } = useAuth();
  // A cold-start tap arrives ~50 ms after mount, before capabilities load, and
  // some routes cannot be resolved without them: `/my-route` is WorkforceRoute
  // or MyRoute by capability (actionRoutes.ts), and with none known it would
  // fall back to the inbox. So the tap is HELD until capabilities are known.
  // (`/incidents` resolves either way: probed on the emulator with the hold
  // removed, it still opened the incident.)
  const [pending, setPending] = useState<Record<string, string> | null>(null);
  // Subscribe ONCE: re-subscribing re-reads getInitialNotification, which the
  // library answers once per message (measured: three subscriptions in four
  // seconds of a cold start before this was a mount-only effect).
  useEffect(() => onPushOpened(setPending), []);
  useEffect(() => {
    if (!pending || !capabilities) return;
    setPending(null);
    refresh();
    if (!pending.link_route) { switchTab(INBOX); return; }
    open({ link: {
      route: pending.link_route,
      kind: pending.link_kind ?? null,
      id: pending.link_id ?? null,
      date: pending.link_date ?? null,
    } });
  }, [pending, capabilities, open, switchTab, refresh]);
  return null;
}

const label = (n: LiveNotification) => n.label || n.type.replace(/_/g, ' ');

/**
 * A strong haptic for URGENT. Android only, guarded like primitives.tick():
 * Vibration throws without the VIBRATE permission, and a haptic must never be
 * able to break the thing it announces. iOS has no haptic without a native
 * module; it gets the visual alone.
 */
function urgentHaptic() {
  if (Platform.OS !== 'android') return;
  try { Vibration.vibrate([0, 60, 80, 60]); } catch { /* silence is the degradation */ }
}

// ─── Top: URGENT cards + the "need you" row ─────────────────────────────────

export function NotificationTopArea() {
  const c = useColors(); const s = styles(c);
  const insets = useSafeAreaInsets();
  const { unread, markRead } = useNotifications();
  const open = useOpen();
  const [sheet, setSheet] = useState<'actions' | 'urgent' | null>(null);

  const { urgent, needsYou: actions } = partitionArea(unread);
  const { pinned, overflow } = capUrgent(urgent);
  if (!urgent.length && !actions.length) return null;

  const u = urgentStyle(c);
  return (
    <View style={[s.top, { paddingTop: insets.top + spacing.xs }]}>
      {pinned.map(n => (
        // Not a live region and not dismissable: a card to ACT on (ADR-487 D4a).
        <View key={n.id} style={[s.urgent, { backgroundColor: u.bg, borderLeftColor: u.border, borderLeftWidth: u.barWidth }]}
          accessibilityRole="alert">
          <View style={s.headRow}>
            <Text style={[s.urgentTitle, { color: u.text }]} numberOfLines={1}>
              {n.icon ? `${n.icon} ` : ''}{label(n)}
            </Text>
            <Text style={s.when}>{formatRelative(n.created_at)}</Text>
          </View>
          <Text style={s.urgentMsg} numberOfLines={2}>{n.message}</Text>
          <Pressable style={[s.urgentBtn, { borderColor: u.border }]}
            accessibilityRole="button"
            // Read BEFORE navigating: the destination fetches on focus, and
            // navigating first let that fetch beat the PATCH (seen on the emulator).
            onPress={async () => { await markRead([n.id]); open(n); }}>
            <Text style={[s.urgentBtnText, { color: u.text }]}>{n.actions?.[0]?.label ?? 'Open'}</Text>
          </Pressable>
        </View>
      ))}
      {overflow.length > 0 && (
        <Pressable style={[s.needRow, { backgroundColor: u.bg, borderLeftColor: u.border, borderLeftWidth: u.barWidth }]}
          onPress={() => setSheet('urgent')}
          accessibilityRole="button"
          accessibilityLabel={`${overflow.length} more urgent. Open the list.`}>
          <Text style={s.needIcon}>🚨</Text>
          <Text style={[s.needText, { color: u.text }]}>{overflow.length} more urgent</Text>
          <Text style={s.chev}>›</Text>
        </Pressable>
      )}
      {actions.length > 0 && (
        <Pressable style={s.needRow} onPress={() => setSheet('actions')}
          accessibilityRole="button"
          accessibilityLabel={`${actions.length} ${actions.length === 1 ? 'item needs' : 'items need'} you. Open the list.`}>
          <Text style={s.needIcon}>✋</Text>
          <Text style={s.needText}>{actions.length} need{actions.length === 1 ? 's' : ''} you</Text>
          <Text style={s.chev}>›</Text>
        </Pressable>
      )}
      <ActionSheet visible={sheet !== null} title={sheet === 'urgent' ? 'Urgent' : 'Needs you'}
        items={sheet === 'urgent' ? overflow : actions} onClose={() => setSheet(null)}
        onAct={async n => { setSheet(null); await markRead([n.id]); open(n); }} />
    </View>
  );
}

function ActionSheet({ visible, title, items, onClose, onAct }: {
  visible: boolean; title: string; items: LiveNotification[]; onClose: () => void; onAct: (n: LiveNotification) => void;
}) {
  const c = useColors(); const s = styles(c);
  const insets = useSafeAreaInsets();
  const reduced = useReducedMotionState();
  return (
    <Modal visible={visible} transparent animationType={reduced ? 'none' : 'slide'} onRequestClose={onClose}>
      <Pressable style={s.scrim} onPress={onClose} accessibilityLabel="Close" />
      <View style={[s.sheet, { paddingBottom: insets.bottom + spacing.md }]}>
        <View style={s.grabber} />
        <Text style={s.sheetTitle}>{title}</Text>
        <ScrollView style={s.sheetList}>
          {items.map(n => {
            const t = toneStyle(n.tone ?? 'neutral', c);
            return (
              <View key={n.id} style={s.sheetRow}>
                <View style={s.grow}>
                  <View style={s.headRow}>
                    <Text style={[s.sheetLabel, { color: t.text }]}>{n.icon ? `${n.icon} ` : ''}{label(n)}</Text>
                    <Text style={s.when}>{formatRelative(n.created_at)}</Text>
                  </View>
                  <Text style={s.sheetMsg} numberOfLines={3}>{n.message}</Text>
                </View>
                <Pressable style={[s.sheetBtn, { backgroundColor: c.brand }]} accessibilityRole="button"
                  onPress={() => onAct(n)}>
                  <Text style={[s.sheetBtnText, { color: c.brandForeground }]}>{n.actions?.[0]?.label ?? 'Open'}</Text>
                </Pressable>
              </View>
            );
          })}
          {items.length === 0 && <Text style={s.sheetMsg}>Nothing needs you right now.</Text>}
        </ScrollView>
      </View>
    </Modal>
  );
}

// ─── Bottom: the ticker dock ────────────────────────────────────────────────

export function NotificationTickerDock() {
  const c = useColors(); const s = styles(c);
  const { unread, markRead } = useNotifications();
  const switchTab = useTabSwitch();
  const items = partitionArea(unread).ticker;
  if (!items.length) return null;
  return (
    <View style={s.dock}>
      <NotificationTicker
        items={items.map(n => ({ id: n.id, message: n.message, icon: n.icon, label: n.label }))}
        onPress={() => switchTab(INBOX)}
        onDismissAll={() => markRead(items.map(n => n.id))}
      />
    </View>
  );
}

// ─── Arrival: the slide-down banner, by tier ────────────────────────────────

export function ArrivalBanner() {
  const c = useColors(); const s = styles(c);
  const { isDark } = useTheme();
  const insets = useSafeAreaInsets();
  const reduced = useReducedMotionState();
  const { arrivals, clearArrivals } = useNotifications();
  const open = useOpen();
  const [shown, setShown] = useState<LiveNotification | null>(null);
  const slide = useRef(new Animated.Value(0)).current;   // 0 hidden, 1 shown
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const hide = useCallback(() => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    if (reduced) { slide.setValue(0); setShown(null); return; }
    Animated.timing(slide, { toValue: 0, duration: 180, easing: Easing.in(Easing.quad), useNativeDriver: true })
      .start(() => setShown(null));
  }, [reduced, slide]);

  useEffect(() => {
    if (!arrivals.length) return;
    // D2's tiers. URGENT goes to the pinned region (which re-renders on its
    // own) with a strong haptic; ticker types just join the ticker; everything
    // else that is new gets the banner, newest first.
    const { urgentHaptic: buzz, banner: next } = arrivalOutcome(arrivals);
    if (buzz) urgentHaptic();
    clearArrivals();
    if (!next) return;

    tick();   // light haptic (Android), guarded
    AccessibilityInfo.announceForAccessibility(`${label(next)}. ${next.message}`);
    setShown(next);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    if (reduced) slide.setValue(1);
    else Animated.timing(slide, { toValue: 1, duration: 240, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
    hideTimer.current = setTimeout(hide, BANNER_MS);
  }, [arrivals, clearArrivals, hide, reduced, slide]);

  useEffect(() => () => { if (hideTimer.current) clearTimeout(hideTimer.current); }, []);

  if (!shown) return null;
  const t = toneStyle(shown.tone ?? 'neutral', c);
  const translateY = slide.interpolate({ inputRange: [0, 1], outputRange: [-140, 0] });
  return (
    <Animated.View
      pointerEvents="box-none"
      style={[s.bannerWrap, { paddingTop: insets.top + spacing.xs },
        reduced ? { opacity: slide } : { transform: [{ translateY }] }]}>
      <Pressable
        // elevate(): a shadow on light, a lifted surface on dark (theme rule).
        style={[s.banner, elevate(3, c, isDark), { borderLeftColor: t.border }]}
        accessibilityRole="button"
        accessibilityLabel={`${label(shown)}. ${shown.message}. Opens it.`}
        onPress={() => { hide(); open(shown); }}>
        <Text style={[s.bannerTitle, { color: t.text }]} numberOfLines={1}>{shown.icon ? `${shown.icon} ` : ''}{label(shown)}</Text>
        <Text style={s.bannerMsg} numberOfLines={2}>{shown.message}</Text>
      </Pressable>
    </Animated.View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  top: {
    backgroundColor: c.background, paddingHorizontal: spacing.sm, paddingBottom: spacing.xs, gap: spacing.xs,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.border,
  },
  urgent: { borderRadius: radius.md, padding: spacing.sm, gap: 2 },
  headRow: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: spacing.sm },
  when: { fontSize: fontSize.xs, color: c.mutedForeground, flexShrink: 0 },
  urgentTitle: { flexShrink: 1, fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  urgentMsg: { fontSize: fontSize.sm, color: c.foreground },
  urgentBtn: {
    alignSelf: 'flex-end', marginTop: spacing.xs, borderWidth: 1, borderRadius: radius.md,
    paddingHorizontal: spacing.md, minHeight: MIN_TARGET, justifyContent: 'center',
  },
  urgentBtnText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  needRow: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.xs, minHeight: MIN_TARGET,
    paddingHorizontal: spacing.md, borderRadius: radius.md, backgroundColor: c.infoLight,
  },
  needIcon: { fontSize: fontSize.base },
  needText: { flex: 1, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground },
  chev: { fontSize: fontSize.lg, color: c.mutedForeground },
  scrim: { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)' },   // the scrim InterruptiveSheet uses
  sheet: {
    backgroundColor: c.card, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.md, paddingTop: spacing.sm, maxHeight: '70%',
  },
  grabber: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: c.border, marginBottom: spacing.sm },
  sheetTitle: { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground, marginBottom: spacing.sm },
  sheetList: { flexGrow: 0 },
  sheetRow: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: c.border,
  },
  grow: { flex: 1 },
  sheetLabel: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  sheetMsg: { fontSize: fontSize.sm, color: c.mutedForeground },
  sheetBtn: { borderRadius: radius.md, paddingHorizontal: spacing.md, minHeight: MIN_TARGET, justifyContent: 'center' },
  sheetBtnText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  dock: { paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, backgroundColor: c.background },
  bannerWrap: { position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: spacing.sm, zIndex: 50, elevation: 12 },
  banner: {
    backgroundColor: c.card, borderRadius: radius.lg, padding: spacing.md, gap: 2, borderLeftWidth: 4,
    borderWidth: StyleSheet.hairlineWidth, borderColor: c.border,
  },
  bannerTitle: { fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  bannerMsg: { fontSize: fontSize.sm, color: c.foreground },
});
