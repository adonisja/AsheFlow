/**
 * Two-factor enrolment for mobile (ADR-381 D2).
 *
 * The web has SecurityPanel; mobile had nothing, so the PreAuthentication
 * trigger's message -- "open AsheFlow on the web and go to Account > Security"
 * -- sent a walker whose only device is a phone to find a computer.
 *
 * EMAIL FIRST, deliberately. SecurityPanel's own rationale says why: an emailed
 * code needs no app at all and every account already has a verified address,
 * "which matters for field staff, who are being asked to install nothing". On a
 * personal phone, "install an authenticator" is a real ask. TOTP stays for
 * anyone who prefers it.
 *
 * Shared by both surfaces: the blocking screen and the Profile row. One
 * enrolment implementation, so the two cannot drift.
 */
import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, ActivityIndicator, Alert,
  TextInput, ScrollView,
} from 'react-native';
import {
  setUpTOTP, verifyTOTPSetup, updateMFAPreference,
} from 'aws-amplify/auth';

import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type Props = {
  /** Called once a factor is actually enrolled, so the caller can re-fetch. */
  onEnrolled: () => void;
};

export default function MfaEnrolment({ onEnrolled }: Props) {
  const c = useColors();
  const s = styles(c);

  const [busy, setBusy] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const [code, setCode] = useState('');

  /* Email OTP needs no setup step -- the address is already verified, so
     enabling the preference IS the enrolment. */
  const enableEmail = async () => {
    setBusy(true);
    try {
      await updateMFAPreference({ email: 'PREFERRED' });
      onEnrolled();
    } catch (e) {
      // No error detail in the alert: Cognito's messages name internal state
      // and mean nothing to a walker at 05:00.
      Alert.alert('Could not turn on email codes', 'Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const beginTotp = async () => {
    setBusy(true);
    try {
      const out = await setUpTOTP();
      /* The SECRET, not a QR. The authenticator app is on this same phone, so
         there is no second screen to scan from -- the user copies the string
         into the app they are about to switch to. */
      setSecret(out.sharedSecret);
    } catch (e) {
      Alert.alert('Could not start setup', 'Please try again.');
    } finally {
      setBusy(false);
    }
  };

  const confirmTotp = async () => {
    setBusy(true);
    try {
      await verifyTOTPSetup({ code: code.trim() });
      await updateMFAPreference({ totp: 'PREFERRED' });
      onEnrolled();
    } catch (e) {
      Alert.alert('That code did not work', 'Check the app and try again.');
    } finally {
      setBusy(false);
    }
  };

  if (busy) {
    return (
      <View style={s.centre}>
        <ActivityIndicator size="large" color={c.primary} />
      </View>
    );
  }

  if (secret) {
    return (
      <ScrollView contentContainerStyle={s.body} keyboardShouldPersistTaps="handled">
        <Text style={s.heading}>Add this key to your authenticator app</Text>
        <Text selectable style={s.secret}>{secret}</Text>
        <Text style={s.hint}>
          Tap and hold to copy. Open your authenticator app, add an account by
          entering this key, then type the 6-digit code it shows.
        </Text>
        <TextInput
          style={s.input}
          value={code}
          onChangeText={setCode}
          placeholder="000000"
          placeholderTextColor={c.mutedForeground}
          keyboardType="number-pad"
          maxLength={6}
          autoFocus
        />
        <TouchableOpacity
          style={[s.primaryBtn, code.trim().length !== 6 && s.disabled]}
          disabled={code.trim().length !== 6}
          onPress={confirmTotp}
        >
          <Text style={s.primaryBtnText}>Confirm</Text>
        </TouchableOpacity>
        <TouchableOpacity onPress={() => { setSecret(null); setCode(''); }}>
          <Text style={s.link}>Use a different method</Text>
        </TouchableOpacity>
      </ScrollView>
    );
  }

  return (
    <View style={s.body}>
      <TouchableOpacity style={s.primaryBtn} onPress={enableEmail}>
        <Text style={s.primaryBtnText}>Email me a code each sign-in</Text>
      </TouchableOpacity>
      <Text style={s.hint}>
        Nothing to install. Codes go to the address already on your account.
      </Text>

      <TouchableOpacity style={s.secondaryBtn} onPress={beginTotp}>
        <Text style={s.secondaryBtnText}>Use an authenticator app instead</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  centre:  { paddingVertical: spacing.xl * 2, alignItems: 'center' },
  body:    { gap: spacing.md, paddingVertical: spacing.md },
  heading: { fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.foreground },
  secret:  {
    fontSize: fontSize.md, color: c.foreground, letterSpacing: 1,
    backgroundColor: c.accent, padding: spacing.md, borderRadius: radius.md,
  },
  hint:    { fontSize: fontSize.sm, color: c.mutedForeground },
  input:   {
    borderWidth: 1, borderColor: c.border, borderRadius: radius.md,
    padding: spacing.md, fontSize: fontSize.xl, color: c.foreground,
    textAlign: 'center', letterSpacing: 4,
  },
  primaryBtn: {
    backgroundColor: c.primary, padding: spacing.md,
    borderRadius: radius.md, alignItems: 'center',
  },
  primaryBtnText: { color: c.primaryForeground, fontWeight: fontWeight.semibold, fontSize: fontSize.md },
  secondaryBtn: {
    borderWidth: 1, borderColor: c.border, padding: spacing.md,
    borderRadius: radius.md, alignItems: 'center',
  },
  secondaryBtnText: { color: c.foreground, fontWeight: fontWeight.medium, fontSize: fontSize.md },
  disabled: { opacity: 0.5 },
  link:     { color: c.primary, textAlign: 'center', fontSize: fontSize.sm },
});
