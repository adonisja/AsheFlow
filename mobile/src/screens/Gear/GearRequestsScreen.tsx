import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert, Image,
  type ImageSourcePropType,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

/** Field-staff gear ordering — catalogue (season-aware) displayed as an
 * interactive image-card grid → size picker → cart → submit; own order
 * history with per-item status. */

type CatalogueItem = {
  item: string;
  season: string;
  available: boolean;
  sizes: string[];
  no_size: boolean;
};

type OrderItem = {
  id: string;
  item: string;
  size: string | null;
  status: string;
  notes: string | null;
};

type Order = {
  id: string;
  submitted_at: string;
  items: OrderItem[];
};

// ── Gear visual mapping ────────────────────────────────────────────────────
// Keys match the backend catalogue item ids (lowercase — see gear_requests.py
// SIZE_MAP); the previous PascalCase keys never matched, so every card fell
// through to the 📦 default. Product images are the same assets the web gear
// page uses (frontend/public/), copied to src/assets/gear as PNG. RN requires
// static require() calls — dynamic string paths don't bundle.
// Per-item identity colors are intentional brand constants (not theme-semantic),
// so they read the same in light/dark — like the role palette (ADR-207).
const GEAR_META: Record<string, { image: ImageSourcePropType; icon: string; label: string; color: string }> = {
  cap:         { image: require('@assets/gear/cap.png'),         icon: '🧢', label: 'Cap',                color: '#3B82F6' },
  gloves:      { image: require('@assets/gear/gloves.png'),      icon: '🧤', label: 'Gloves',             color: '#8B5CF6' },
  jacket:      { image: require('@assets/gear/jacket.png'),      icon: '🧥', label: 'Jacket',             color: '#64748B' },
  pants:       { image: require('@assets/gear/pants.png'),       icon: '👖', label: 'Pants',              color: '#334155' },
  shirt_long:  { image: require('@assets/gear/shirt_long.png'),  icon: '👔', label: 'Long Sleeve Shirt',  color: '#0EA5E9' },
  shirt_short: { image: require('@assets/gear/shirt_short.png'), icon: '👕', label: 'Short Sleeve Shirt', color: '#10B981' },
  shorts:      { image: require('@assets/gear/shorts.png'),      icon: '🩳', label: 'Shorts',             color: '#F59E0B' },
  vest:        { image: require('@assets/gear/vest.png'),        icon: '🦺', label: 'Safety Vest',        color: '#EF4444' },
};

type GearMeta = { image: ImageSourcePropType | null; icon: string; label: string; color: string };

function gearMeta(item: string): GearMeta {
  return GEAR_META[item] ?? { image: null, icon: '📦', label: item.replace(/_/g, ' '), color: '#6B7280' };
}

// Gear-request status → themed color (ADR-207). (GEAR_META item colors above are
// intentional per-item brand identity, like the role palette — kept as constants.)
function statusColor(status: string, c: ThemeColors): string {
  switch (status) {
    case 'pending':   return c.warning;
    case 'approved':  return c.info;
    case 'fulfilled': return c.success;
    case 'denied':    return c.danger;
    default:          return c.mutedForeground;
  }
}

export default function GearRequestsScreen() {
  const c = useColors();
  const s = styles(c);

  const [loading,    setLoading]    = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [season,     setSeason]     = useState('');
  const [catalogue,  setCatalogue]  = useState<CatalogueItem[]>([]);
  const [orders,     setOrders]     = useState<Order[]>([]);
  const [cart,       setCart]       = useState<Record<string, string | null>>({});
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async (opts?: { refresh?: boolean }) => {
    if (opts?.refresh) setRefreshing(true);
    try {
      const [cat, mine] = await Promise.all([
        apiClient.get('/gear-requests/catalogue'),
        apiClient.get('/gear-requests/my-orders'),
      ]);
      setSeason(cat.data?.current_season ?? '');
      setCatalogue(cat.data?.items ?? []);
      setOrders(mine.data ?? []);
    } catch {
      // pull-to-refresh recovers
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const toggleItem = (it: CatalogueItem) => {
    setCart(prev => {
      const next = { ...prev };
      if (it.item in next) {
        delete next[it.item];
      } else {
        // Sized items start unselected so the customer must pick a size (the
        // submit guard enforces it); no_size items carry null legitimately.
        next[it.item] = null;
      }
      return next;
    });
  };

  const submit = async () => {
    const items = Object.entries(cart).map(([item, size]) => ({ item, size }));
    if (items.length === 0) return;

    // A sized item with no size selected must not ship on a silent default.
    // no_size items (cap) legitimately carry size=null.
    const sizedItems = new Map(catalogue.map(it => [it.item, it]));
    const missingSize = items.filter(({ item, size }) => {
      const cat = sizedItems.get(item);
      return cat && !cat.no_size && !size;
    });
    if (missingSize.length > 0) {
      const names = missingSize.map(m => gearMeta(m.item).label).join(', ');
      Alert.alert('Choose a size', `Select a size for: ${names}.`);
      return;
    }

    setSubmitting(true);
    try {
      await apiClient.post('/gear-requests/', { items });
      setCart({});
      await load();
      Alert.alert('Order submitted', 'Management will review your gear request.');
    } catch (e) {
      Alert.alert('Error', errorText(e, 'Could not submit the order.'));
    } finally {
      setSubmitting(false);
    }
  };

  const cartCount = Object.keys(cart).length;
  const openOrders = orders.filter(o => o.items.some(i => i.status === 'pending' || i.status === 'approved'));
  const pastOrders = orders.filter(o => !openOrders.includes(o));

  // Catalogue split into currently-available items (shown as cards) and
  // out-of-season items (compact rows below).
  const available   = catalogue.filter(it => it.available);
  const unavailable = catalogue.filter(it => !it.available);

  return (
    <ScreenShell
      title="Request Gear"
      subtitle={season ? `${season} season` : undefined}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => load({ refresh: true })}
    >
      {/* Catalogue — 2-column card grid */}
      <View style={s.grid}>
        {available.map(it => {
          const selected = it.item in cart;
          const meta = gearMeta(it.item);
          return (
            <GearCard
              key={it.item}
              item={it}
              meta={meta}
              selected={selected}
              size={cart[it.item] ?? null}
              onToggle={() => toggleItem(it)}
              onSizeChange={size => setCart(prev => ({ ...prev, [it.item]: size }))}
              c={c}
              s={s}
            />
          );
        })}
      </View>

      {/* Unavailable items — compact row at the bottom of catalogue */}
      {unavailable.length > 0 && (
        <>
          <Text style={[s.sectionLabel, { marginTop: spacing.sm }]}>NOT AVAILABLE THIS SEASON</Text>
          <View style={[s.unavailableBox, { backgroundColor: c.card, borderColor: c.border }]}>
            {unavailable.map((it, i) => {
              const meta = gearMeta(it.item);
              return (
                <View
                  key={it.item}
                  style={[s.unavailableRow, i < unavailable.length - 1 && { borderBottomWidth: 1, borderBottomColor: c.border }]}
                >
                  {meta.image
                    ? <Image source={meta.image} style={s.unavailableImage} resizeMode="contain" />
                    : <Text style={s.unavailableIcon}>{meta.icon}</Text>}
                  <View style={{ flex: 1 }}>
                    <Text style={{ fontSize: fontSize.sm, color: c.mutedForeground }}>{meta.label}</Text>
                    <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>{it.season} item</Text>
                  </View>
                </View>
              );
            })}
          </View>
        </>
      )}

      {/* Cart submit CTA */}
      {cartCount > 0 && (
        <TouchableOpacity style={[s.submitBtn, { backgroundColor: c.primary }]} onPress={submit} disabled={submitting}>
          {submitting
            ? <ActivityIndicator color={c.primaryForeground} />
            : <Text style={s.submitBtnText}>Submit Order · {cartCount} item{cartCount === 1 ? '' : 's'}</Text>}
        </TouchableOpacity>
      )}

      {/* My orders */}
      {orders.length > 0 && <Text style={[s.sectionLabel, { marginTop: spacing.md }]}>MY ORDERS</Text>}
      {[...openOrders, ...pastOrders].map(o => (
        <View key={o.id} style={[s.orderCard, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={[s.orderDate, { color: c.mutedForeground }]}>
            {new Date(o.submitted_at).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}
          </Text>
          {o.items.map(it => {
            const meta = gearMeta(it.item);
            return (
              <View key={it.id} style={s.orderItemRow}>
                {meta.image
                  ? <Image source={meta.image} style={s.orderItemImage} resizeMode="contain" />
                  : <Text style={s.orderItemIcon}>{meta.icon}</Text>}
                <Text style={[s.orderItemName, { color: c.foreground, flex: 1 }]}>
                  {meta.label}{it.size ? ` · ${it.size}` : ''}
                </Text>
                <View style={[s.statusChip, { backgroundColor: statusColor(it.status, c) + '1E' }]}>
                  <Text style={[s.statusText, { color: statusColor(it.status, c) }]}>{it.status}</Text>
                </View>
              </View>
            );
          })}
          {o.items.some(it => it.notes) && (
            <Text style={[s.orderNote, { color: c.mutedForeground }]}>
              {o.items.filter(it => it.notes).map(it => `${gearMeta(it.item).label}: ${it.notes}`).join(' · ')}
            </Text>
          )}
        </View>
      ))}
    </ScreenShell>
  );
}

// ── Gear card ──────────────────────────────────────────────────────────────

function GearCard({ item, meta, selected, size, onToggle, onSizeChange, c, s }: {
  item: CatalogueItem;
  meta: GearMeta;
  selected: boolean;
  size: string | null;
  onToggle: () => void;
  onSizeChange: (size: string) => void;
  c: ThemeColors;
  s: ReturnType<typeof styles>;
}) {
  return (
    <TouchableOpacity
      style={[
        s.gearCard,
        { backgroundColor: c.card, borderColor: selected ? meta.color : c.border, borderWidth: selected ? 2 : 1 },
      ]}
      onPress={onToggle}
      activeOpacity={0.75}
    >
      {/* Selection badge */}
      {selected && (
        <View style={[s.selectedBadge, { backgroundColor: meta.color }]}>
          <Text style={{ color: c.primaryForeground, fontSize: 10, fontWeight: '800' }}>✓</Text>
        </View>
      )}

      {/* Icon / image area — product image, emoji fallback for unmapped items */}
      <View style={[s.iconArea, { backgroundColor: selected ? meta.color + '18' : c.surfaceMuted }]}>
        {meta.image
          ? <Image source={meta.image} style={s.gearImage} resizeMode="contain" />
          : <Text style={s.gearIcon}>{meta.icon}</Text>}
      </View>

      {/* Name */}
      <Text style={[s.gearLabel, { color: selected ? meta.color : c.foreground }]} numberOfLines={2}>
        {meta.label}
      </Text>

      {/* Size picker — visible when selected. Full-width wrapping chip grid
          (was a cramped horizontal scroll that hid the size step, so orders
          went out on the default size without the customer choosing). */}
      {selected && !item.no_size && item.sizes.length > 0 && (
        <View style={s.sizeArea}>
          <Text style={[s.sizePrompt, { color: c.mutedForeground }]}>Select a size</Text>
          <View style={s.sizeRow}>
            {item.sizes.map(sz => (
              <TouchableOpacity
                key={sz}
                style={[
                  s.sizeChip,
                  { borderColor: size === sz ? meta.color : c.border },
                  size === sz && { backgroundColor: meta.color + '18' },
                ]}
                onPress={e => { e.stopPropagation?.(); onSizeChange(sz); }}
              >
                <Text style={[s.sizeText, { color: size === sz ? meta.color : c.mutedForeground }]}>{sz}</Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>
      )}

      {/* One-size items (cap) — make it explicit that no size is needed */}
      {selected && item.no_size && (
        <Text style={[s.sizePrompt, { color: c.mutedForeground, marginTop: spacing.xs }]}>One size fits all</Text>
      )}
    </TouchableOpacity>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  sectionLabel:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, letterSpacing: 0.8, marginBottom: spacing.sm, marginTop: spacing.xs },

  // Grid — one item per row (full-width) so the image and size chips have room
  grid:            { marginBottom: spacing.sm, gap: spacing.sm },
  gearCard:        { width: '100%', borderRadius: radius.lg, padding: spacing.md, position: 'relative' },
  selectedBadge:   { position: 'absolute', top: spacing.sm, right: spacing.sm, width: 22, height: 22, borderRadius: 11, alignItems: 'center', justifyContent: 'center', zIndex: 1 },
  iconArea:        { height: 150, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center', marginBottom: spacing.sm },
  gearIcon:        { fontSize: 56 },
  gearImage:       { width: '70%', height: '90%' },
  gearLabel:       { fontSize: fontSize.base, fontWeight: fontWeight.semibold, textAlign: 'center', lineHeight: 20 },
  sizeArea:        { marginTop: spacing.sm },
  sizePrompt:      { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textAlign: 'center', marginBottom: spacing.xs, letterSpacing: 0.4 },
  sizeRow:         { flexDirection: 'row', flexWrap: 'wrap', justifyContent: 'center', gap: spacing.xs },
  sizeChip:        { borderWidth: 1, borderRadius: radius.full, paddingHorizontal: spacing.md, paddingVertical: spacing.xs + 1, minWidth: 44, alignItems: 'center' },
  sizeText:        { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  // Unavailable
  unavailableBox:  { borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden', marginBottom: spacing.sm },
  unavailableRow:  { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  unavailableIcon: { fontSize: 22, opacity: 0.4 },
  unavailableImage:{ width: 28, height: 28, opacity: 0.5 },

  // Submit
  submitBtn:       { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', marginBottom: spacing.md },
  submitBtnText:   { color: c.primaryForeground, fontSize: fontSize.sm, fontWeight: fontWeight.bold },

  // Orders
  orderCard:       { borderRadius: radius.lg, borderWidth: 1, padding: spacing.md, marginBottom: spacing.sm },
  orderDate:       { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, marginBottom: spacing.xs },
  orderItemRow:    { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 4 },
  orderItemIcon:   { fontSize: 18, width: 24, textAlign: 'center' },
  orderItemImage:  { width: 24, height: 24 },
  orderItemName:   { fontSize: fontSize.sm },
  statusChip:      { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  statusText:      { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  orderNote:       { fontSize: fontSize.xs, marginTop: spacing.xs, fontStyle: 'italic' },
});
