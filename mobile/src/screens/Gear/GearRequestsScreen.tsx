import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert, ScrollView,
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

// ── Gear icon / visual mapping ────────────────────────────────────────────
// Each item gets an emoji icon and a descriptive label. The icon doubles as
// the visual anchor for the card — a real product image URL could replace it
// once backend serves asset URLs.
const GEAR_META: Record<string, { icon: string; label: string; color: string }> = {
  Cap:        { icon: '🧢', label: 'Cap',             color: '#3B82F6' },
  Gloves:     { icon: '🧤', label: 'Gloves',          color: '#8B5CF6' },
  Jacket:     { icon: '🧥', label: 'Jacket',          color: '#64748B' },
  Pants:      { icon: '👖', label: 'Pants',           color: '#334155' },
  Shirt_Long: { icon: '👔', label: 'Long Sleeve Shirt', color: '#0EA5E9' },
  Shirt_Short:{ icon: '👕', label: 'Short Sleeve Shirt', color: '#10B981' },
  Shorts:     { icon: '🩳', label: 'Shorts',          color: '#F59E0B' },
  Vest:       { icon: '🦺', label: 'Safety Vest',     color: '#EF4444' },
};

function gearMeta(item: string) {
  return GEAR_META[item] ?? { icon: '📦', label: item.replace(/_/g, ' '), color: '#6B7280' };
}

const STATUS_COLORS: Record<string, string> = {
  pending: '#E8820C', approved: '#0EA5D8', fulfilled: '#0FA870', denied: '#E8443A',
};

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
        next[it.item] = it.no_size ? null : (it.sizes[0] ?? null);
      }
      return next;
    });
  };

  const submit = async () => {
    const items = Object.entries(cart).map(([item, size]) => ({ item, size }));
    if (items.length === 0) return;
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

  // Build grid rows (2 columns)
  const available   = catalogue.filter(it => it.available);
  const unavailable = catalogue.filter(it => !it.available);

  return (
    <ScreenShell
      edges={[]} noHeader
      title="Gear"
      subtitle={season ? `${season} season` : undefined}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => load({ refresh: true })}
    >
      {/* Catalogue — 2-column card grid */}
      <Text style={s.sectionLabel}>REQUEST GEAR</Text>

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
                  <Text style={s.unavailableIcon}>{meta.icon}</Text>
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
            ? <ActivityIndicator color="#fff" />
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
                <Text style={s.orderItemIcon}>{meta.icon}</Text>
                <Text style={[s.orderItemName, { color: c.foreground, flex: 1 }]}>
                  {meta.label}{it.size ? ` · ${it.size}` : ''}
                </Text>
                <View style={[s.statusChip, { backgroundColor: (STATUS_COLORS[it.status] ?? c.mutedForeground) + '1E' }]}>
                  <Text style={[s.statusText, { color: STATUS_COLORS[it.status] ?? c.mutedForeground }]}>{it.status}</Text>
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
  meta: { icon: string; label: string; color: string };
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
          <Text style={{ color: '#fff', fontSize: 10, fontWeight: '800' }}>✓</Text>
        </View>
      )}

      {/* Icon / image area */}
      <View style={[s.iconArea, { backgroundColor: selected ? meta.color + '18' : c.surfaceMuted }]}>
        <Text style={s.gearIcon}>{meta.icon}</Text>
      </View>

      {/* Name */}
      <Text style={[s.gearLabel, { color: selected ? meta.color : c.foreground }]} numberOfLines={2}>
        {meta.label}
      </Text>

      {/* Size picker — only visible when selected and sizes exist */}
      {selected && !item.no_size && item.sizes.length > 0 && (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={{ marginTop: spacing.xs }}
          contentContainerStyle={{ gap: 5, paddingBottom: 2 }}
          onStartShouldSetResponder={() => true}
        >
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
        </ScrollView>
      )}
    </TouchableOpacity>
  );
}

// ── Styles ─────────────────────────────────────────────────────────────────

const styles = (c: ThemeColors) => StyleSheet.create({
  sectionLabel:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, letterSpacing: 0.8, marginBottom: spacing.sm, marginTop: spacing.xs },

  // Grid
  grid:            { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm, marginBottom: spacing.sm },
  gearCard:        { width: '47%', borderRadius: radius.lg, padding: spacing.sm, position: 'relative', minHeight: 130 },
  selectedBadge:   { position: 'absolute', top: spacing.xs, right: spacing.xs, width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center', zIndex: 1 },
  iconArea:        { height: 72, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center', marginBottom: spacing.xs },
  gearIcon:        { fontSize: 36 },
  gearLabel:       { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textAlign: 'center', lineHeight: 16 },
  sizeChip:        { borderWidth: 1, borderRadius: radius.full, paddingHorizontal: spacing.sm, paddingVertical: 3 },
  sizeText:        { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  // Unavailable
  unavailableBox:  { borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden', marginBottom: spacing.sm },
  unavailableRow:  { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  unavailableIcon: { fontSize: 22, opacity: 0.4 },

  // Submit
  submitBtn:       { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', marginBottom: spacing.md },
  submitBtnText:   { color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.bold },

  // Orders
  orderCard:       { borderRadius: radius.lg, borderWidth: 1, padding: spacing.md, marginBottom: spacing.sm },
  orderDate:       { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, marginBottom: spacing.xs },
  orderItemRow:    { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 4 },
  orderItemIcon:   { fontSize: 18, width: 24, textAlign: 'center' },
  orderItemName:   { fontSize: fontSize.sm },
  statusChip:      { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  statusText:      { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  orderNote:       { fontSize: fontSize.xs, marginTop: spacing.xs, fontStyle: 'italic' },
});
