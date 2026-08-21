/**
 * ADR-277 D3 — buildings on my truck (mobile).
 *
 * The operator's reason for building this on mobile as well as web: sign-off
 * happens in the field, "while viewing the data in real time". A captain
 * standing in front of the building is the person best placed to confirm what
 * it is — asking them to remember it until they are back at a desk is how the
 * observation gets lost.
 *
 * Three groups, ordered by what a captain can act on: sign-offs they owe,
 * addresses nobody has profiled, then the known set for reference.
 */
import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  TouchableOpacity,
  ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { type ThemeColors } from '@theme/index';

type TruckBuildingStop = {
  normalised_address: string | null;
  block_key: string;
  segment_id: string | null;
  stop_count: number;
  profile: {
    id: string;
    building_type: string;
    building_type_status: string;
    operational_note: string | null;
    address_status: string;
    geo_message: string | null;
    remaining_weight: number | null;
    can_verify: boolean | null;
  } | null;
};

type TruckBuildings = {
  route_date: string;
  truck_name: string | null;
  needs_signoff: TruckBuildingStop[];
  known: TruckBuildingStop[];
  no_profile: TruckBuildingStop[];
  no_truck_assigned: boolean;
};

const TYPE_LABELS: Record<string, string> = {
  mailroom: 'Mail room',
  receptionist: 'Receptionist',
  doorman: 'Doorman',
  walkup: 'Walk-up',
  elevator: 'Elevator',
  biz_front: 'Business — front desk',
  biz_freight: 'Business — freight',
  biz_security: 'Business — security',
  biz_loading_dock: 'Business — loading dock',
};

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function StopRow({ stop, c }: { stop: TruckBuildingStop; c: ThemeColors }) {
  const p = stop.profile;
  // ADR-219 nulls the address at 48h; block_key survives, so the stop still
  // counts — there is just no address left to print.
  const label = stop.normalised_address ?? `${stop.block_key} (address expired)`;

  return (
    <View style={[s.row, { borderBottomColor: c.border }]}>
      <View style={s.rowMain}>
        <Text style={[s.addr, { color: c.foreground }]} numberOfLines={1}>
          {label}
        </Text>
        <Text style={[s.meta, { color: c.mutedForeground }]}>
          {stop.block_key}
          {stop.stop_count > 1 ? ` · ${stop.stop_count} visits` : ''}
          {p ? ` · ${TYPE_LABELS[p.building_type] ?? p.building_type}` : ''}
        </Text>
        {p?.operational_note ? (
          <Text style={[s.note, { color: c.mutedForeground }]} numberOfLines={2}>
            {p.operational_note}
          </Text>
        ) : null}
        {p?.address_status === 'rejected' ? (
          <Text style={[s.note, { color: c.warning }]}>
            Address not found{p.geo_message ? ` — ${p.geo_message}` : ''}
          </Text>
        ) : null}
      </View>

      <View style={s.rowRight}>
        {p ? (
          <>
            <Text style={[s.status, { color: c.mutedForeground }]}>{p.building_type_status}</Text>
            {/* ADR-276 D6: remaining weight, not a raw count. */}
            {typeof p.remaining_weight === 'number' && p.remaining_weight > 0 ? (
              <Text style={[s.remaining, { color: c.mutedForeground }]}>
                {p.remaining_weight === 1 ? '1 more' : `${p.remaining_weight} more`}
              </Text>
            ) : null}
          </>
        ) : (
          <Text style={[s.status, { color: c.primary }]}>Not profiled</Text>
        )}
      </View>
    </View>
  );
}

function Group({
  title,
  subtitle,
  stops,
  emptyText,
  c,
}: {
  title: string;
  subtitle: string;
  stops: TruckBuildingStop[];
  emptyText: string;
  c: ThemeColors;
}) {
  return (
    <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
      <View style={s.cardHead}>
        <Text style={[s.cardTitle, { color: c.foreground }]}>{title}</Text>
        <Text style={[s.count, { color: c.mutedForeground }]}>{stops.length}</Text>
      </View>
      <Text style={[s.cardSub, { color: c.mutedForeground }]}>{subtitle}</Text>
      {stops.length === 0 ? (
        <Text style={[s.empty, { color: c.mutedForeground }]}>{emptyText}</Text>
      ) : (
        stops.map((st) => (
          <StopRow key={st.normalised_address ?? `${st.block_key}-${st.stop_count}`} stop={st} c={c} />
        ))
      )}
    </View>
  );
}

export default function TruckBuildingsScreen() {
  const c = useColors();
  const [data, setData] = useState<TruckBuildings | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const res = await apiClient.get<TruckBuildings>(
        `/building-profiles/for-truck/${todayISO()}`,
      );
      setData(res.data);
    } catch (e) {
      setError(errorText(e, 'Could not load buildings for your truck.'));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void load();
  }, [load]);

  return (
    <ScreenShell title="Truck buildings">
      {loading ? (
        <View style={s.center}>
          <ActivityIndicator color={c.primary} />
        </View>
      ) : (
        <ScrollView
          contentContainerStyle={s.scroll}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={c.primary} />
          }
        >
          {error ? (
            <View style={[s.card, { backgroundColor: c.card, borderColor: c.danger }]}>
              <Text style={{ color: c.danger }}>{error}</Text>
              <TouchableOpacity onPress={onRefresh} style={s.retry}>
                <Text style={{ color: c.primary, fontWeight: '600' }}>Retry</Text>
              </TouchableOpacity>
            </View>
          ) : !data ? null : data.no_truck_assigned ? (
            /* A state, not an error — three empty lists would read as "every
               building on your route is already profiled". */
            <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
              <Text style={[s.cardTitle, { color: c.foreground }]}>No truck assigned today</Text>
              <Text style={[s.cardSub, { color: c.mutedForeground }]}>
                This page shows the buildings on the truck you are crewed on.
              </Text>
            </View>
          ) : (
            <>
              {data.truck_name ? (
                <Text style={[s.truck, { color: c.mutedForeground }]}>Truck {data.truck_name}</Text>
              ) : null}
              <Group
                c={c}
                title="Needs your sign-off"
                subtitle="The field agreed. One route lead confirms it."
                stops={data.needs_signoff}
                emptyText="Nothing waiting on you."
              />
              <Group
                c={c}
                title="No profile yet"
                subtitle="Your truck delivered here and nobody has recorded what it is like."
                stops={data.no_profile}
                emptyText="Every address on this truck has a profile."
              />
              <Group
                c={c}
                title="Known"
                subtitle="Verified intelligence your crew can rely on."
                stops={data.known}
                emptyText="Nothing verified for this truck yet."
              />
            </>
          )}
        </ScrollView>
      )}
    </ScreenShell>
  );
}

const s = StyleSheet.create({
  scroll: { padding: 12, gap: 12 },
  center: { paddingVertical: 48, alignItems: 'center' },
  truck: { fontSize: 12, marginBottom: 2 },
  card: { borderWidth: 1, borderRadius: 12, padding: 14, marginBottom: 12 },
  cardHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  cardTitle: { fontSize: 14, fontWeight: '700' },
  cardSub: { fontSize: 12, marginTop: 2 },
  count: { fontSize: 12, fontWeight: '700' },
  empty: { fontSize: 12, marginTop: 10 },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth },
  rowMain: { flex: 1, minWidth: 0 },
  rowRight: { alignItems: 'flex-end' },
  addr: { fontSize: 14, fontWeight: '600' },
  meta: { fontSize: 11, marginTop: 2 },
  note: { fontSize: 11, marginTop: 3 },
  status: { fontSize: 10, fontWeight: '700', textTransform: 'uppercase' },
  remaining: { fontSize: 10, marginTop: 2 },
  retry: { marginTop: 8 },
});
