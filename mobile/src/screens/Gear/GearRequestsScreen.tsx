import React, { useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

/** Field-staff gear ordering — mirrors the web /gear page on the
 * /gear-requests API: catalogue (season-aware) → cart → submit; own order
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
  status: string;    // pending | approved | denied | fulfilled
  notes: string | null;
};

type Order = {
  id: string;
  submitted_at: string;
  items: OrderItem[];
};

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
  const [cart,       setCart]       = useState<Record<string, string | null>>({});  // item → size
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

  return (
    <ScreenShell
      edges={[]} noHeader
      title="Gear"
      subtitle={season ? `Current season: ${season}` : undefined}
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => load({ refresh: true })}
    >
      {/* Catalogue */}
      <Text style={s.sectionLabel}>REQUEST GEAR</Text>
      <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
        {catalogue.map((it, i) => {
          const selected = it.item in cart;
          return (
            <View key={it.item} style={[s.itemRow, i < catalogue.length - 1 && { borderBottomWidth: 1, borderBottomColor: c.border }]}>
              <TouchableOpacity
                style={s.itemMain}
                onPress={() => it.available && toggleItem(it)}
                disabled={!it.available}
                activeOpacity={0.7}
              >
                <View style={[s.checkbox, { borderColor: selected ? c.primary : c.border }, selected && { backgroundColor: c.primary }]}>
                  {selected && <Text style={s.checkboxMark}>✓</Text>}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[s.itemName, { color: it.available ? c.foreground : c.mutedForeground }]}>
                    {it.item}
                  </Text>
                  {!it.available && (
                    <Text style={[s.itemUnavailable, { color: c.mutedForeground }]}>
                      {it.season} item — not available this season
                    </Text>
                  )}
                </View>
              </TouchableOpacity>
              {/* Size picker appears once selected */}
              {selected && !it.no_size && (
                <View style={s.sizeRow}>
                  {it.sizes.map(size => (
                    <TouchableOpacity
                      key={size}
                      style={[s.sizeChip, { borderColor: c.border }, cart[it.item] === size && { backgroundColor: c.primaryLight, borderColor: c.primary }]}
                      onPress={() => setCart(prev => ({ ...prev, [it.item]: size }))}
                    >
                      <Text style={[s.sizeText, { color: cart[it.item] === size ? c.primary : c.mutedForeground }]}>{size}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
              )}
            </View>
          );
        })}
      </View>

      {cartCount > 0 && (
        <TouchableOpacity style={[s.submitBtn, { backgroundColor: c.primary }]} onPress={submit} disabled={submitting}>
          {submitting
            ? <ActivityIndicator color="#fff" />
            : <Text style={s.submitBtnText}>Submit Order · {cartCount} item{cartCount === 1 ? '' : 's'}</Text>}
        </TouchableOpacity>
      )}

      {/* My orders */}
      {orders.length > 0 && <Text style={s.sectionLabel}>MY ORDERS</Text>}
      {[...openOrders, ...pastOrders].map(o => (
        <View key={o.id} style={[s.card, { backgroundColor: c.card, borderColor: c.border, padding: spacing.md, marginBottom: spacing.sm }]}>
          <Text style={[s.orderDate, { color: c.mutedForeground }]}>
            {new Date(o.submitted_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
          </Text>
          {o.items.map(it => (
            <View key={it.id} style={s.orderItemRow}>
              <Text style={[s.orderItemName, { color: c.foreground }]}>
                {it.item}{it.size ? ` · ${it.size}` : ''}
              </Text>
              <View style={[s.statusChip, { backgroundColor: (STATUS_COLORS[it.status] ?? c.mutedForeground) + '1E' }]}>
                <Text style={[s.statusText, { color: STATUS_COLORS[it.status] ?? c.mutedForeground }]}>{it.status}</Text>
              </View>
            </View>
          ))}
          {o.items.some(it => it.notes) && (
            <Text style={[s.orderNote, { color: c.mutedForeground }]}>
              {o.items.filter(it => it.notes).map(it => `${it.item}: ${it.notes}`).join(' · ')}
            </Text>
          )}
        </View>
      ))}
    </ScreenShell>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  sectionLabel: { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, letterSpacing: 0.8, marginBottom: spacing.xs, marginTop: spacing.sm },
  card:         { borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden', marginBottom: spacing.sm },
  itemRow:      { paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  itemMain:     { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  checkbox:     { width: 20, height: 20, borderRadius: 6, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  checkboxMark: { color: '#fff', fontSize: 12, fontWeight: '700' },
  itemName:     { fontSize: fontSize.sm, fontWeight: fontWeight.medium, textTransform: 'capitalize' },
  itemUnavailable: { fontSize: fontSize.xs, marginTop: 1 },
  sizeRow:      { flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: spacing.xs, marginLeft: 32 },
  sizeChip:     { borderWidth: 1, borderRadius: radius.full, paddingHorizontal: spacing.sm + 2, paddingVertical: 3 },
  sizeText:     { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  submitBtn:    { borderRadius: radius.md, paddingVertical: spacing.sm + 2, alignItems: 'center', marginBottom: spacing.md },
  submitBtnText:{ color: '#fff', fontSize: fontSize.sm, fontWeight: fontWeight.bold },
  orderDate:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, marginBottom: spacing.xs },
  orderItemRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 3 },
  orderItemName:{ fontSize: fontSize.sm, textTransform: 'capitalize' },
  statusChip:   { paddingHorizontal: spacing.sm, paddingVertical: 2, borderRadius: radius.full },
  statusText:   { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'capitalize' },
  orderNote:    { fontSize: fontSize.xs, marginTop: spacing.xs, fontStyle: 'italic' },
});
