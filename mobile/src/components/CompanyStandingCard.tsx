/**
 * The DSP's Amazon standing — a shared fact, shown to every role.
 *
 * Tier 1 in docs/SCORECARD_ACCESS_MODEL.md: `GET /scorecards/company/current`
 * is gated to ALL roles and returns no PII whatsoever — a week, a standing, and
 * the direction of travel. A walker learns where the company stands without
 * seeing anyone's individual numbers, which is the whole reason this is a
 * separate endpoint from the Tier 3 roster.
 *
 * Deliberately a component and not a screen: the standing is context for
 * whatever you were already doing, not a destination. It renders nothing at all
 * when there is no scorecard yet, so it cannot leave an empty card on a
 * new company's home screen.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator } from 'react-native';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type Standing = {
  week: string | null;
  standing: string | null;
  previous_standing: string | null;
  /** improved | declined | unchanged | null */
  direction: string | null;
  /** Weeks held at the CURRENT standing, not a total. */
  consecutive_weeks: number;
  has_data: boolean;
};

/**
 * Amazon's standings, best to worst. Fantastic > Great > Fair > Poor > At Risk.
 * Colour is semantic (ADR-207) so it tracks the theme rather than hard-coding.
 */
function standingColor(s: string | null, c: ThemeColors): string {
  switch ((s || '').toLowerCase()) {
    case 'fantastic':      return c.success;
    case 'great':          return c.info;
    case 'fair':           return c.gold;
    case 'poor':           return c.warning;
    case 'at risk':
    case 'at_risk':        return c.danger;
    default:               return c.mutedForeground;
  }
}

function directionLabel(d: string | null, prev: string | null): string | null {
  if (d === 'improved')  return prev ? `Up from ${prev}` : 'Improved';
  if (d === 'declined')  return prev ? `Down from ${prev}` : 'Declined';
  return null;
}

export default function CompanyStandingCard() {
  const c = useColors();
  const s = styles(c);

  const [data, setData] = useState<Standing | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get<Standing>('/scorecards/company/current');
      setData(res.data);
      setFailed(false);
    } catch {
      // Context, not the point of the screen — a failure here must never
      // surface an error banner over whatever the user actually opened.
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  if (loading) {
    return (
      <View style={[s.card, s.centered]}>
        <ActivityIndicator color={c.primary} />
      </View>
    );
  }

  // No scorecard uploaded yet, or the fetch failed. Render nothing rather than
  // an empty shell — this is supplementary context on someone else's screen.
  if (failed || !data?.has_data) return null;

  const tone = standingColor(data.standing, c);
  const dir = directionLabel(data.direction, data.previous_standing);

  return (
    <View style={s.card}>
      <View style={s.row}>
        <Text style={s.label}>Company standing</Text>
        {data.week && <Text style={s.week}>{data.week}</Text>}
      </View>

      <Text style={[s.standing, { color: tone }]}>{data.standing ?? '—'}</Text>

      <View style={s.row}>
        {dir && <Text style={s.meta}>{dir}</Text>}
        {data.consecutive_weeks > 1 && (
          <Text style={s.meta}>
            {data.consecutive_weeks} weeks running
          </Text>
        )}
      </View>
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  card: {
    backgroundColor: c.card,
    borderColor: c.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.xs,
  },
  centered: { alignItems: 'center', justifyContent: 'center', minHeight: 80 },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
  },
  label: {
    color: c.mutedForeground,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.medium,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
  week: { color: c.mutedForeground, fontSize: fontSize.sm },
  standing: { fontSize: fontSize.xl, fontWeight: fontWeight.bold },
  meta: { color: c.mutedForeground, fontSize: fontSize.sm },
});
