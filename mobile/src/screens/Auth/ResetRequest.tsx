/**
 * "Can't use your authenticator?" on mobile (ADR-551 D1).
 *
 * Same two steps as the web: a code to the account's verified email proves the
 * inbox owner is asking, then the request goes to whoever can reset this
 * account (their company's admins, AsheFlow support, or a super admin). It
 * never resets anything itself.
 */
import React, { useState } from 'react';
import { StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Button } from '@components/ui/primitives';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type Step = 'closed' | 'start' | 'code' | 'done';

export default function ResetRequest({ username }: { username: string }) {
  const c = useColors();
  const s = styles(c);
  const [step, setStep] = useState<Step>('closed');
  // The username they just typed; not asked again. The server resolves it to
  // the account's permanent ID and keeps the request by that ID.
  const name = username;
  const [code, setCode] = useState('');
  // ADR-551 D2b: the server's ticket from step 1. Unreadable here; it is what
  // tells step 2 which account, so the name is never sent again.
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState('');

  const send = async () => {
    setBusy(true); setError(null);
    try {
      const { data } = await apiClient.post<{ request_token: string }>('/auth/mfa-reset/request', { username: name.trim() });
      setToken(data.request_token);
      setStep('code');
    } catch (err) {
      setError(errorText(err, 'Could not send the code. Try again.'));
    } finally { setBusy(false); }
  };

  const confirm = async () => {
    setBusy(true); setError(null);
    try {
      const { data } = await apiClient.post<{ detail: string }>('/auth/mfa-reset/confirm',
        { request_token: token, code: code.trim() });
      setResult(data.detail); setStep('done');
    } catch (err) {
      setError(errorText(err, 'Could not send the request. Try again.'));
    } finally { setBusy(false); }
  };

  if (step === 'closed') {
    return (
      <TouchableOpacity onPress={() => setStep('start')} accessibilityRole="button"
                        style={s.link}>
        <Text style={[s.linkText, { color: c.primary }]}>Can't use your authenticator? Request a reset</Text>
      </TouchableOpacity>
    );
  }

  return (
    <View style={s.box} accessibilityLiveRegion="polite">
      <Text style={s.title}>Request a two-factor reset</Text>
      {step === 'start' && (
        <>
          <Text style={s.body}>
            We'll email a code to your account's address. Enter it here and your request goes to whoever
            can reset your account. Nothing changes until they do.
          </Text>
          <Text style={s.body}>For <Text style={{ color: c.foreground, fontWeight: fontWeight.semibold }}>{name}</Text></Text>
          {error && <Text style={s.error}>{error}</Text>}
          <Button onPress={() => void send()} loading={busy} disabled={!name.trim()} fullWidth>Email me a code</Button>
          <Button variant="ghost" onPress={() => setStep('closed')}>Cancel</Button>
        </>
      )}
      {step === 'code' && (
        <>
          <Text style={s.body}>If that account has a verified email, a code is on its way. It works once, for 10 minutes.</Text>
          <TextInput style={[s.input, s.code]} value={code} onChangeText={t => { setCode(t); setError(null); }}
                     keyboardType="number-pad" textContentType="oneTimeCode" autoComplete="one-time-code"
                     maxLength={6} accessibilityLabel="Code from the email"
                     placeholder="000000" placeholderTextColor={c.placeholder} />
          {error && <Text style={s.error}>{error}</Text>}
          <Button onPress={() => void confirm()} loading={busy} disabled={code.trim().length < 6} fullWidth>Send the request</Button>
          <Button variant="ghost" onPress={() => setStep('start')}>Back</Button>
        </>
      )}
      {step === 'done' && <Text style={s.body}>{result}</Text>}
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  link:     { marginTop: spacing.md, alignItems: 'center', paddingVertical: spacing.sm },
  linkText: { fontSize: fontSize.sm, fontWeight: fontWeight.medium },
  box:      { marginTop: spacing.md, borderWidth: 1, borderColor: c.border, borderRadius: radius.md,
              padding: spacing.md, gap: spacing.sm },
  title:    { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.foreground },
  body:     { fontSize: fontSize.sm, color: c.mutedForeground, lineHeight: 20 },
  input:    { borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm + 2, fontSize: fontSize.base, color: c.foreground },
  code:     { letterSpacing: 6 },
  error:    { fontSize: fontSize.sm, color: c.danger },
});
