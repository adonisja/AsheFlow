/**
 * Platform support on mobile (ADR-549 D6).
 *
 * Support's pages (onboarding surveyors, survey activity) exist only on the
 * web. Before this, a support account signing in to the app fell through to
 * the TENANT tab shell, every tab of which calls employee endpoints that 403
 * for an account with no Employee row. Say where the work is, and offer the
 * one thing that works here: signing out.
 */
import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import { Button } from '@components/ui/primitives';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, type ThemeColors } from '@theme/index';

export default function PlatformSupportScreen() {
  const c = useColors();
  const s = styles(c);
  const { signOut } = useAuth();
  return (
    <ScreenShell title="Platform support" subtitle="Works on the web">
      <View style={s.body}>
        <Text style={s.text}>
          Onboarding surveyors and survey activity are on the web. Sign in at
          asheflow.com on a computer or in your phone's browser.
        </Text>
        <Button variant="ghost" onPress={() => void signOut()}>Sign out</Button>
      </View>
    </ScreenShell>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  body: { padding: spacing.lg, gap: spacing.lg },
  text: { fontSize: fontSize.base, color: c.foreground, lineHeight: 22 },
});
