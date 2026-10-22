/**
 * My account for platform accounts on mobile (ADR-549 D6).
 *
 * Surveyors (and the platform owner) sign in to the survey shell, which had no
 * account or security screen: no way to change a password and nowhere to set
 * up the second factor that ADR-549 D1 now requires. The tenant account screen
 * is built on an Employee row these accounts do not have, so this one talks to
 * /platform/me. Same flow as web and as ADR-541: a code to the inbox, then
 * signed out everywhere, this phone included.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Platform, StyleSheet, Text, TextInput, View } from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import { Button } from '@components/ui/primitives';
import MfaEnrolment from '@components/MfaEnrolment';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type PlatformMe = {
  account_id: string; surveyor_id: string | null;   // ADR-550 D1
  username: string; name: string | null; email: string | null; email_verified: boolean;
  groups: string[]; role_label: string; mfa_enrolled: boolean | null;
};

export default function PlatformAccountScreen({ navigation }: { navigation: { goBack: () => void } }) {
  const c = useColors();
  const s = styles(c);
  const { signOut, refreshMfaStatus } = useAuth();

  const [me, setMe] = useState<PlatformMe | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [step, setStep] = useState<'idle' | 'code'>('idle');
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await apiClient.get<PlatformMe>('/platform/me');
      setMe(data); setLoadError(null);
    } catch (err) {
      setLoadError(errorText(err, 'Could not load your account.'));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const requestCode = async () => {
    setError(null); setBusy(true);
    try {
      const { data } = await apiClient.post<{ sent_to: string | null }>('/platform/me/password/request-code');
      setSentTo(data.sent_to); setStep('code');
    } catch (err) {
      setError(errorText(err, 'Could not send the code. Try again.'));
    } finally { setBusy(false); }
  };

  const submit = async () => {
    setError(null);
    if (code.trim().length < 6) { setError('Enter the 6-digit code from the email.'); return; }
    if (next !== confirm) { setError('New passwords do not match.'); return; }
    if (next.length < 8) { setError('Password must be at least 8 characters.'); return; }
    setBusy(true);
    try {
      await apiClient.post('/platform/me/password/confirm', { code: code.trim(), new_password: next });
      Alert.alert('Password changed', 'You were signed out everywhere. Sign in with your new password.',
                  [{ text: 'Sign in again', onPress: () => void signOut() }], { cancelable: false });
    } catch (err) {
      setError(errorText(err, 'Could not change your password. Try again.'));
      setBusy(false);
    }
  };

  const noEmail = me !== null && (!me.email || !me.email_verified);

  // ADR-563 D2: change your own email -- a code to the current address and one
  // to the new. The server writes Cognito, ends every session and tells the old
  // address, so this phone is signed out too.
  const [eStep, setEStep] = useState<'idle' | 'entering' | 'verifying'>('idle');
  const [newEmail, setNewEmail] = useState('');
  const [eCodes, setECodes] = useState({ current: '', new: '' });
  const [eMasked, setEMasked] = useState<{ current: string; new: string } | null>(null);
  const [eError, setEError] = useState<string | null>(null);
  const [eBusy, setEBusy] = useState(false);
  const resetEmail = () => { setEStep('idle'); setNewEmail(''); setECodes({ current: '', new: '' }); setEError(null); };

  const requestEmail = async () => {
    if (!newEmail.includes('@')) { setEError('Enter a valid email address.'); return; }
    setEBusy(true); setEError(null);
    try {
      const { data } = await apiClient.post<{ current_masked: string; new_masked: string }>(
        '/platform/me/email/request-change', { new_email: newEmail.trim().toLowerCase() });
      setEMasked({ current: data.current_masked, new: data.new_masked }); setEStep('verifying');
    } catch (err) {
      setEError(errorText(err, 'Could not send the codes.'));
    } finally { setEBusy(false); }
  };

  const confirmEmail = async () => {
    if (eCodes.current.trim().length < 6 || eCodes.new.trim().length < 6) { setEError('Enter both 6-digit codes.'); return; }
    setEBusy(true); setEError(null);
    try {
      await apiClient.post('/platform/me/email/confirm-change',
                           { current_code: eCodes.current.trim(), new_code: eCodes.new.trim() });
      Alert.alert('Email changed', 'You were signed out everywhere. Your old address was told about the change.',
                  [{ text: 'Sign in again', onPress: () => void signOut() }], { cancelable: false });
    } catch (err) {
      setEError(errorText(err, 'Could not verify the codes.'));
      setEBusy(false);
    }
  };

  return (
    <ScreenShell title="My account" subtitle={me?.role_label} onBack={() => navigation.goBack()}
                 onRefresh={load} keyboardInsets>
      <View style={s.card}>
        <Text style={s.h2}>Profile</Text>
        {loadError ? <Text style={s.error}>{loadError}</Text> : !me ? <Text style={s.muted}>Loading…</Text> : (
          <>
            <Text style={s.body}>{me.name || me.username}</Text>
            <Text style={s.muted}>{me.username}</Text>
            <Text style={s.muted}>{me.email ?? 'No email on file'}{me.email && !me.email_verified ? ' (not verified)' : ''}</Text>
            {/* ADR-550 D1: the IDs support asks for -- names repeat, these don't.
                selectable so they can be copied with the system long-press. */}
            {me.surveyor_id && <Text style={s.mono} selectable>Surveyor ID {me.surveyor_id}</Text>}
            <Text style={s.mono} selectable>Account ID {me.account_id}</Text>
          </>
        )}
        <Text style={s.hint}>A super admin sets platform names.</Text>
      </View>

      <View style={s.card}>
        <Text style={s.h2}>Change email</Text>
        {noEmail ? (
          <Text style={s.muted}>There's no verified email to confirm the change from. Ask a super admin to change it for you.</Text>
        ) : eStep === 'idle' ? (
          <>
            <Text style={s.muted}>We'll email a code to your current address and one to the new address. After the change you'll be signed out everywhere, including this phone.</Text>
            <Button variant="secondary" onPress={() => { setEStep('entering'); setEError(null); }} disabled={!me} fullWidth>Change email</Button>
          </>
        ) : eStep === 'entering' ? (
          <>
            <TextInput style={s.input} value={newEmail} onChangeText={t => { setNewEmail(t); setEError(null); }}
                       placeholder="New email address" placeholderTextColor={c.placeholder}
                       keyboardType="email-address" autoCapitalize="none" autoCorrect={false}
                       textContentType="emailAddress" autoComplete="email" accessibilityLabel="New email address" />
            {eError && <Text style={s.error}>{eError}</Text>}
            <Button onPress={() => void requestEmail()} loading={eBusy} fullWidth>Send codes</Button>
            <Button variant="ghost" onPress={resetEmail}>Cancel</Button>
          </>
        ) : (
          <>
            <Text style={s.muted}>Code sent to {eMasked?.current ?? 'your current email'}</Text>
            <TextInput style={[s.input, s.code]} value={eCodes.current}
                       onChangeText={t => { setECodes(v => ({ ...v, current: t })); setEError(null); }}
                       placeholder="000000" placeholderTextColor={c.placeholder} keyboardType="number-pad"
                       maxLength={6} accessibilityLabel="Code sent to your current email" />
            <Text style={s.muted}>Code sent to {eMasked?.new ?? 'the new email'}</Text>
            <TextInput style={[s.input, s.code]} value={eCodes.new}
                       onChangeText={t => { setECodes(v => ({ ...v, new: t })); setEError(null); }}
                       placeholder="000000" placeholderTextColor={c.placeholder} keyboardType="number-pad"
                       maxLength={6} accessibilityLabel="Code sent to the new email" />
            <Text style={s.hint}>Codes expire in 10 minutes.</Text>
            {eError && <Text style={s.error}>{eError}</Text>}
            <Button onPress={() => void confirmEmail()} loading={eBusy} fullWidth>Confirm</Button>
            <Button variant="ghost" onPress={resetEmail}>Cancel</Button>
          </>
        )}
      </View>

      <View style={s.card}>
        <Text style={s.h2}>Change password</Text>
        {noEmail ? (
          <Text style={s.muted}>Changing your password needs a verified email address. Ask a super admin to change it.</Text>
        ) : step === 'idle' ? (
          <>
            <Text style={s.muted}>We'll email a code to your address. After the change you'll be signed out everywhere, including this phone.</Text>
            {error && <Text style={s.error}>{error}</Text>}
            <Button onPress={() => void requestCode()} loading={busy} disabled={!me} fullWidth>Email me a code</Button>
          </>
        ) : (
          <>
            <Text style={s.muted}>Code sent{sentTo ? ` to ${sentTo}` : ''}. It works once.</Text>
            <TextInput style={[s.input, s.code]} value={code} onChangeText={t => { setCode(t); setError(null); }}
                       placeholder="000000" placeholderTextColor={c.placeholder} keyboardType="number-pad"
                       textContentType="oneTimeCode" autoComplete="sms-otp" maxLength={6}
                       accessibilityLabel="Code from the email" />
            <TextInput style={s.input} value={next} onChangeText={t => { setNext(t); setError(null); }}
                       placeholder="New password" placeholderTextColor={c.placeholder} secureTextEntry
                       textContentType="newPassword" autoComplete="password-new" accessibilityLabel="New password" />
            <TextInput style={s.input} value={confirm} onChangeText={t => { setConfirm(t); setError(null); }}
                       placeholder="Confirm new password" placeholderTextColor={c.placeholder} secureTextEntry
                       textContentType="newPassword" autoComplete="password-new" accessibilityLabel="Confirm new password" />
            <Text style={s.hint}>At least 8 characters, with upper and lower case letters, a number and a symbol.</Text>
            {error && <Text style={s.error}>{error}</Text>}
            <Button onPress={() => void submit()} loading={busy} fullWidth>Change password</Button>
            <Button variant="ghost" onPress={() => { setStep('idle'); setCode(''); setError(null); }}>Cancel</Button>
          </>
        )}
      </View>

      <View style={s.card}>
        <Text style={s.h2}>Two-factor authentication</Text>
        {me?.mfa_enrolled
          ? <Text style={s.muted}>Your account is protected by a second factor.</Text>
          : <MfaEnrolment onEnrolled={() => { void refreshMfaStatus(); void load(); }} />}
      </View>
    </ScreenShell>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  card:  { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border,
           padding: spacing.md, marginBottom: spacing.md, gap: spacing.sm },
  h2:    { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.foreground },
  body:  { fontSize: fontSize.base, color: c.foreground },
  muted: { fontSize: fontSize.sm, color: c.mutedForeground, lineHeight: 20 },
  hint:  { fontSize: fontSize.xs, color: c.mutedForeground },
  mono:  { fontSize: fontSize.xs, color: c.mutedForeground, fontFamily: Platform.select({ ios: 'Menlo', default: 'monospace' }) },
  error: { fontSize: fontSize.sm, color: c.danger },
  input: { borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: spacing.md,
           paddingVertical: spacing.sm + 2, fontSize: fontSize.base, color: c.foreground, backgroundColor: c.background },
  code:  { letterSpacing: 6, fontVariant: ['tabular-nums'] },
});
