/**
 * The wall, for a user whose grace period has closed (ADR-381 D2).
 *
 * A full screen swapped in at the ROOT NAVIGATOR, not a modal over the tab
 * shell. RootNavigator already chooses between MainShell and LoginScreen on
 * `isAuthenticated`; this is the same idiom for the same reason -- "you cannot
 * be in the app yet". A modal would leave the tabs reachable behind it, which
 * is not what blocked means.
 *
 * The web banner does not port here. A dismissible strip works on a desktop
 * where it stays in the viewport; on a phone it is one swipe from gone, and a
 * walker opening the app to check today's route never scrolls back up.
 *
 * No dismiss, no back. There is nothing to come back to -- the
 * PreAuthentication trigger already refuses them at sign-in, so this screen is
 * their only explanation and their only way out.
 */
import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import MfaEnrolment from '@components/MfaEnrolment';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, fontSize, fontWeight, type ThemeColors } from '@theme/index';

export default function MfaRequiredScreen() {
  const c = useColors();
  const s = styles(c);
  const { refreshMfaStatus, signOut } = useAuth();

  return (
    <SafeAreaView style={s.safe}>
      <ScrollView contentContainerStyle={s.container} keyboardShouldPersistTaps="handled">
        {/* Says what is now true and what clears it. Not "MFA enforcement
            active", which tells a walker nothing they can act on. */}
        <Text style={s.title}>Set up two-factor authentication</Text>
        <Text style={s.body}>
          Your account needs a second sign-in step before you can keep using
          AsheFlow. It takes about a minute.
        </Text>

        <MfaEnrolment onEnrolled={refreshMfaStatus} />

        {/* Sign out is the only other exit. Offered because a shared phone
            with the wrong account signed in would otherwise be stuck here with
            no way to reach the login screen. */}
        <TouchableOpacity onPress={signOut} style={s.signOut}>
          <Text style={s.signOutText}>Sign out</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:      { flex: 1, backgroundColor: c.background },
  container: { padding: spacing.lg, gap: spacing.md, flexGrow: 1 },
  title:     { fontSize: fontSize.xxl, fontWeight: fontWeight.bold, color: c.foreground },
  body:      { fontSize: fontSize.md, color: c.mutedForeground, lineHeight: 22 },
  signOut:   { marginTop: spacing.xl, alignItems: 'center' },
  signOutText: { color: c.mutedForeground, fontSize: fontSize.sm },
});
