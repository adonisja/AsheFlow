import React, { useCallback, useState } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import GuideBody from './GuideBody';

/**
 * "What does my role do here?" — the mobile half of ADR-494 D4.
 *
 * Same endpoint and same content as the web page: `GET /my-role` answers for
 * the caller's own role and the company's current operating mode, so neither
 * client passes a role and neither can ask about someone else's.
 *
 * ## Why this is a tab and not a push inside Home
 *
 * It is the destination of a notification. `graduation` and
 * `operating_mode_change` both link here, and a screen reachable only by first
 * knowing which tab it hides under is not a destination — the prompt's action
 * has to be able to land on it directly, which on this navigator means a tab
 * key `useTabSwitch` can set.
 *
 * ## Not mode-gated
 *
 * No `feature:` gate in TAB_GATES, deliberately. The row is keyed by
 * (company, role, mode) and the server returns the one matching the CURRENT
 * mode, so a tenant who switches finds the other set already written. Gating
 * this tab on a capability would hide the destination of the very notification
 * that announces the switch.
 */

type RoleGuide = {
  role: string;
  operating_mode: 'full' | 'workforce';
  title: string;
  body: string;
  is_customized: boolean;
};

export default function MyRoleScreen() {
  const c = useColors();
  const s = styles(c);
  const [guide, setGuide] = useState<RoleGuide | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.get<RoleGuide>('/my-role');
      setGuide(res.data);
    } catch (e: unknown) {
      // A 404 is a real, distinct state — a role whose guide was never seeded —
      // and the server's message tells the reader to ask an admin. errorText
      // surfaces that detail and falls back for anything else.
      setError(errorText(e, 'We could not load your role guide. Try again in a moment.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { void load(); }, [load]));

  return (
    <ScreenShell
      title={guide?.title ?? 'Your role'}
      subtitle={
        guide
          ? guide.operating_mode === 'full'
            ? 'This company runs with an Amazon package feed.'
            : 'This company runs without an Amazon package feed.'
          : undefined
      }
      loading={loading}
      refreshing={false}
      onRefresh={() => void load()}
    >
      {error && (
        <View style={s.errorCard}>
          <Text style={s.errorTitle}>No guide to show</Text>
          <Text style={s.errorBody}>{error}</Text>
        </View>
      )}

      {guide && (
        <>
          <GuideBody body={guide.body} />
          {/* Shown to everyone, not just admins. A field user who finds
              something here that does not match their lot should know the text
              is their company's to fix, rather than assuming the app is wrong
              about them. */}
          <Text style={s.footnote}>
            {guide.is_customized
              ? 'Your company wrote this guide.'
              : 'This is the standard guide. Your company can edit it in settings.'}
          </Text>
        </>
      )}
    </ScreenShell>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  errorCard: {
    backgroundColor: c.warningLight,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  errorTitle: {
    fontSize: fontSize.base,
    fontWeight: fontWeight.semibold,
    color: c.foreground,
    marginBottom: spacing.xs,
  },
  errorBody: { fontSize: fontSize.sm, color: c.mutedForeground },
  footnote: {
    marginTop: spacing.lg,
    paddingTop: spacing.md,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: c.surfaceMuted,
    fontSize: fontSize.xs,
    color: c.subtleForeground,
  },
});
