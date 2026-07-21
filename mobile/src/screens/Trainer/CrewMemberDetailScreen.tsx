import React, { useState, useCallback } from 'react';
import { View, Text } from 'react-native';
import { useFocusEffect, useNavigation, useRoute, type RouteProp } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import RouteStopsDetailed, { type DetailedStop } from '@components/route/RouteStopsDetailed';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight } from '@theme/index';
import { Badge } from '@components/ui/primitives';
import type { RouteSortStackParamList } from '@navigation/index';

/** Per-employee route detail (ADR-216 phase 2). Current stop at top, then
 * remaining, then completed — each section clearly marked. Consumes
 * GET /walker-routes/routes/{id}/detail. Mirrors what My Route will show. */

type RouteDetail = {
  id: string;
  route_number: number;
  route_date: string;
  status: string;
  effort_class: string;
  executor: { id: string; name: string } | null;
  supervisors: { id: string; name: string }[];
  package_count: number;
  stops: DetailedStop[];
};

const SECTIONS: { key: DetailedStop['lifecycle']; label: string }[] = [
  { key: 'current',   label: 'Current stop' },
  { key: 'remaining', label: 'Remaining' },
  { key: 'completed', label: 'Completed' },
];

export default function CrewMemberDetailScreen() {
  const c = useColors();
  const nav = useNavigation();
  const { params } = useRoute<RouteProp<RouteSortStackParamList, 'CrewMemberDetail'>>();
  const { routeId, memberName } = params;

  const [detail, setDetail] = useState<RouteDetail | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get(`/walker-routes/routes/${routeId}/detail`);
      setDetail(res.data);
    } catch (e) {
      // Non-fatal; screen shows the empty state below.
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [routeId]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const stopsFor = (lifecycle: DetailedStop['lifecycle']) =>
    (detail?.stops ?? []).filter(s => s.lifecycle === lifecycle);

  return (
    <ScreenShell
      title={memberName}
      subtitle={detail ? `Route #${detail.route_number} · ${detail.package_count} packages · ${detail.effort_class}` : undefined}
      onBack={() => nav.goBack()}
      loading={loading}
    >
      {!detail ? (
        <View style={{ padding: spacing.lg }}>
          <Text style={{ color: c.mutedForeground, textAlign: 'center' }}>No route detail available.</Text>
        </View>
      ) : (
        <View style={{ gap: spacing.md }}>
          {detail.supervisors.length > 0 && (
            <Text style={{ fontSize: fontSize.xs, color: c.mutedForeground }}>
              Supervised by {detail.supervisors.map(s => s.name).join(', ')}
            </Text>
          )}
          {SECTIONS.map(section => {
            const stops = stopsFor(section.key);
            if (stops.length === 0) return null;
            const tone = section.key === 'current' ? 'info' : section.key === 'completed' ? 'success' : 'neutral';
            return (
              <View
                key={section.key}
                style={{
                  backgroundColor: c.card, borderRadius: radius.md, borderWidth: 1,
                  borderColor: section.key === 'current' ? c.info + '55' : c.border,
                  padding: spacing.md,
                }}
              >
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.sm }}>
                  <Text style={{ fontSize: fontSize.base, fontWeight: fontWeight.bold, color: c.foreground }}>
                    {section.label}
                  </Text>
                  <Badge tone={tone as any}>{stops.length}</Badge>
                </View>
                <RouteStopsDetailed stops={stops} c={c} />
              </View>
            );
          })}
        </View>
      )}
    </ScreenShell>
  );
}
