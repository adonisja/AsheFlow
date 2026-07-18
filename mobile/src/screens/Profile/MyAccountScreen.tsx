import React, { useState } from 'react';
import { errorText } from '@api/errorText';
import {
  View, Text, StyleSheet, TouchableOpacity,
  ScrollView, TextInput, Alert, ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useAuth } from '@contexts/AuthContext';
import { useColors, useTheme } from '@contexts/ThemeContext';
import apiClient from '@api/client';
import { COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID } from '@env';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import PageHeader from '@components/ui/PageHeader';
import MyPerformanceCard from '@components/MyPerformanceCard';
import ScorecardCard from '@components/ScorecardCard';

const REGION           = (COGNITO_USER_POOL_ID ?? 'us-east-2_').split('_')[0];
const COGNITO_ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;
const CLIENT_ID        = COGNITO_CLIENT_ID ?? '';

type EmailStep    = 'idle' | 'entering' | 'verifying';
type PasswordStep = 'idle' | 'open';

export default function MyAccountScreen() {
  const c = useColors();
  const { isDark, isSystemTheme, setTheme } = useTheme();
  const { user, signOut } = useAuth();
  const s = styles(c);

  // Email edit
  const [emailStep,    setEmailStep]    = useState<EmailStep>('idle');
  const [newEmail,     setNewEmail]     = useState('');
  const [code,         setCode]         = useState('');
  const [emailBusy,    setEmailBusy]    = useState(false);
  const [currentEmail, setCurrentEmail] = useState(user?.email ?? '');

  // Password change
  const [pwStep,     setPwStep]     = useState<PasswordStep>('idle');
  const [currentPw,  setCurrentPw]  = useState('');
  const [newPw,      setNewPw]      = useState('');
  const [confirmPw,  setConfirmPw]  = useState('');
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew,     setShowNew]     = useState(false);
  const [pwBusy,     setPwBusy]     = useState(false);

  // ── Email handlers ──────────────────────────────────────────────────────────

  const requestEmailChange = async () => {
    if (!newEmail.trim() || !newEmail.includes('@')) {
      Alert.alert('Invalid email', 'Enter a valid email address.');
      return;
    }
    setEmailBusy(true);
    try {
      const accessToken = await AsyncStorage.getItem('asheflow_access_token');
      if (!accessToken) throw new Error('Not authenticated');
      await apiClient.post('/employees/me/email/request-change', {
        access_token: accessToken,
        new_email: newEmail.trim().toLowerCase(),
      });
      setEmailStep('verifying');
    } catch (e: any) {
      Alert.alert('Error', errorText(e, e.message ?? 'Could not send verification code.'));
    } finally {
      setEmailBusy(false);
    }
  };

  const confirmEmailChange = async () => {
    if (code.trim().length < 6) {
      Alert.alert('Invalid code', 'Enter the 6-digit code sent to your new email.');
      return;
    }
    setEmailBusy(true);
    try {
      const accessToken = await AsyncStorage.getItem('asheflow_access_token');
      if (!accessToken) throw new Error('Not authenticated');
      await apiClient.post('/employees/me/email/confirm-change', {
        access_token: accessToken,
        code: code.trim(),
        new_email: newEmail.trim().toLowerCase(),
      });
      setCurrentEmail(newEmail.trim().toLowerCase());
      setEmailStep('idle');
      setNewEmail('');
      setCode('');
      Alert.alert('Done', 'Email updated. Sign in again to refresh your session.', [
        { text: 'Sign out now', onPress: signOut },
        { text: 'Later', style: 'cancel' },
      ]);
    } catch (e: any) {
      Alert.alert('Error', errorText(e, e.message ?? 'Could not verify code.'));
    } finally {
      setEmailBusy(false);
    }
  };

  const cancelEmail = () => { setEmailStep('idle'); setNewEmail(''); setCode(''); };

  // ── Password handler ────────────────────────────────────────────────────────

  const handleChangePassword = async () => {
    if (!currentPw.trim() || !newPw.trim()) {
      Alert.alert('Required', 'Fill in all password fields.');
      return;
    }
    if (newPw !== confirmPw) {
      Alert.alert('Mismatch', 'New password and confirmation do not match.');
      return;
    }
    if (newPw.length < 8) {
      Alert.alert('Too short', 'Password must be at least 8 characters.');
      return;
    }
    setPwBusy(true);
    try {
      const accessToken = await AsyncStorage.getItem('asheflow_access_token');
      if (!accessToken) throw new Error('Not authenticated');
      const res = await fetch(COGNITO_ENDPOINT, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-amz-json-1.1',
          'X-Amz-Target': 'AWSCognitoIdentityProviderService.ChangePassword',
        },
        body: JSON.stringify({
          AccessToken:      accessToken,
          PreviousPassword: currentPw,
          ProposedPassword: newPw,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        const t = data.__type ?? '';
        if (t === 'NotAuthorizedException')  { Alert.alert('Wrong password', 'Current password is incorrect.'); return; }
        if (t === 'InvalidPasswordException') { Alert.alert('Invalid password', data.message ?? 'Password does not meet requirements.'); return; }
        Alert.alert('Error', data.message ?? 'Could not change password.');
        return;
      }
      Alert.alert('Password updated', 'Your password has been changed.');
      setCurrentPw(''); setNewPw(''); setConfirmPw('');
      setPwStep('idle');
    } catch {
      Alert.alert('Error', 'Could not change password. Check your connection.');
    } finally {
      setPwBusy(false);
    }
  };

  const cancelPassword = () => {
    setPwStep('idle');
    setCurrentPw(''); setNewPw(''); setConfirmPw('');
    setShowCurrent(false); setShowNew(false);
  };

  // ── Theme picker ────────────────────────────────────────────────────────────

  type ThemeOption = 'light' | 'system' | 'dark';
  const activeTheme: ThemeOption = isSystemTheme ? 'system' : isDark ? 'dark' : 'light';

  const pickTheme = (opt: ThemeOption) => {
    if (opt === 'system') { setTheme(null);    return; }
    if (opt === 'dark')   { setTheme('dark');  return; }
    if (opt === 'light')  { setTheme('light'); return; }
  };

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <SafeAreaView style={s.safe} edges={['top']}>
      {/* hideToggle: this screen has its own System/Light/Dark control in the body */}
      <PageHeader title="My Account" hideToggle />

      <ScrollView contentContainerStyle={s.content} keyboardShouldPersistTaps="handled">

        {/* ── Account section ── */}
        <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>Account</Text>
        <View style={[s.section, { backgroundColor: c.card, borderColor: c.border }]}>

          {/* Username row */}
          <View style={[s.row, s.rowBorder, { borderBottomColor: c.border }]}>
            <Text style={[s.rowLabel, { color: c.mutedForeground }]}>Username</Text>
            <Text style={[s.rowValue, { color: c.foreground }]}>@{user?.username ?? '—'}</Text>
          </View>

          {/* Email row */}
          {emailStep === 'idle' && (
            <TouchableOpacity
              style={s.row}
              onPress={() => { setNewEmail(currentEmail); setEmailStep('entering'); }}
              activeOpacity={0.7}
            >
              <Text style={[s.rowLabel, { color: c.mutedForeground }]}>Email</Text>
              <View style={s.rowRight}>
                <Text style={[s.rowValue, { color: c.foreground }]} numberOfLines={1}>{currentEmail || '—'}</Text>
                <Text style={[s.editChip, { color: c.primary }]}>Edit</Text>
              </View>
            </TouchableOpacity>
          )}

          {emailStep === 'entering' && (
            <View style={s.editBlock}>
              <Text style={[s.editLabel, { color: c.foreground }]}>New email address</Text>
              <TextInput
                style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.surfaceMuted }]}
                value={newEmail}
                onChangeText={setNewEmail}
                placeholder="new@email.com"
                placeholderTextColor={c.mutedForeground}
                keyboardType="email-address"
                autoCapitalize="none"
                autoCorrect={false}
                autoFocus
              />
              <Text style={[s.editHint, { color: c.mutedForeground }]}>
                A verification code will be sent to the new address.
              </Text>
              <View style={s.editActions}>
                <TouchableOpacity onPress={cancelEmail} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.mutedForeground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={requestEmailChange}
                  disabled={emailBusy}
                  style={[s.editBtn, s.editBtnPrimary, { backgroundColor: c.primary, opacity: emailBusy ? 0.6 : 1 }]}
                >
                  {emailBusy
                    ? <ActivityIndicator size="small" color="#fff" />
                    : <Text style={[s.editBtnText, { color: '#fff' }]}>Send Code</Text>}
                </TouchableOpacity>
              </View>
            </View>
          )}

          {emailStep === 'verifying' && (
            <View style={s.editBlock}>
              <Text style={[s.editLabel, { color: c.foreground }]}>Verification code</Text>
              <Text style={[s.editHint, { color: c.mutedForeground }]}>
                Enter the 6-digit code sent to {newEmail}
              </Text>
              <TextInput
                style={[s.input, s.codeInput, { color: c.foreground, borderColor: c.border, backgroundColor: c.surfaceMuted }]}
                value={code}
                onChangeText={setCode}
                placeholder="000000"
                placeholderTextColor={c.mutedForeground}
                keyboardType="number-pad"
                maxLength={6}
                autoFocus
              />
              <View style={s.editActions}>
                <TouchableOpacity onPress={cancelEmail} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.mutedForeground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={() => { setEmailStep('entering'); setCode(''); }} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.primary }]}>Resend</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={confirmEmailChange}
                  disabled={emailBusy || code.length < 6}
                  style={[s.editBtn, s.editBtnPrimary, { backgroundColor: c.primary, opacity: (emailBusy || code.length < 6) ? 0.5 : 1 }]}
                >
                  {emailBusy
                    ? <ActivityIndicator size="small" color="#fff" />
                    : <Text style={[s.editBtnText, { color: '#fff' }]}>Confirm</Text>}
                </TouchableOpacity>
              </View>
            </View>
          )}
        </View>

        {/* ── Performance: official Amazon Scorecard (ADR-204) + our live stats (ADR-203) ── */}
        <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>Performance</Text>
        <ScorecardCard />
        <MyPerformanceCard />

        {/* ── Security section ── */}
        <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>Security</Text>
        <View style={[s.section, { backgroundColor: c.card, borderColor: c.border }]}>

          {pwStep === 'idle' ? (
            <TouchableOpacity style={s.row} onPress={() => setPwStep('open')} activeOpacity={0.7}>
              <Text style={[s.rowLabel, { color: c.mutedForeground }]}>Password</Text>
              <View style={s.rowRight}>
                <Text style={[s.rowValue, { color: c.foreground }]}>••••••••</Text>
                <Text style={[s.editChip, { color: c.primary }]}>Change</Text>
              </View>
            </TouchableOpacity>
          ) : (
            <View style={s.editBlock}>
              {/* Current password */}
              <View style={s.pwField}>
                <Text style={[s.editLabel, { color: c.foreground }]}>Current password</Text>
                <View style={[s.pwInputRow, { borderColor: c.border, backgroundColor: c.surfaceMuted }]}>
                  <TextInput
                    style={[s.pwInput, { color: c.foreground }]}
                    secureTextEntry={!showCurrent}
                    placeholder="Enter current password"
                    placeholderTextColor={c.mutedForeground}
                    value={currentPw}
                    onChangeText={setCurrentPw}
                    autoCapitalize="none"
                    autoFocus
                  />
                  <TouchableOpacity onPress={() => setShowCurrent(v => !v)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                    <Text style={[s.showHide, { color: c.primary }]}>{showCurrent ? 'Hide' : 'Show'}</Text>
                  </TouchableOpacity>
                </View>
              </View>

              {/* New password */}
              <View style={s.pwField}>
                <Text style={[s.editLabel, { color: c.foreground }]}>New password</Text>
                <View style={[s.pwInputRow, { borderColor: c.border, backgroundColor: c.surfaceMuted }]}>
                  <TextInput
                    style={[s.pwInput, { color: c.foreground }]}
                    secureTextEntry={!showNew}
                    placeholder="At least 8 characters"
                    placeholderTextColor={c.mutedForeground}
                    value={newPw}
                    onChangeText={setNewPw}
                    autoCapitalize="none"
                  />
                  <TouchableOpacity onPress={() => setShowNew(v => !v)} hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}>
                    <Text style={[s.showHide, { color: c.primary }]}>{showNew ? 'Hide' : 'Show'}</Text>
                  </TouchableOpacity>
                </View>
              </View>

              {/* Confirm */}
              <View style={s.pwField}>
                <Text style={[s.editLabel, { color: c.foreground }]}>Confirm new password</Text>
                <View style={[s.pwInputRow, {
                  borderColor: confirmPw.length > 0 && confirmPw !== newPw ? c.danger : c.border,
                  backgroundColor: c.surfaceMuted,
                }]}>
                  <TextInput
                    style={[s.pwInput, { color: c.foreground }]}
                    secureTextEntry
                    placeholder="Re-enter new password"
                    placeholderTextColor={c.mutedForeground}
                    value={confirmPw}
                    onChangeText={setConfirmPw}
                    autoCapitalize="none"
                  />
                </View>
                {confirmPw.length > 0 && confirmPw !== newPw && (
                  <Text style={s.errorText}>Passwords do not match</Text>
                )}
              </View>

              <View style={s.editActions}>
                <TouchableOpacity onPress={cancelPassword} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.mutedForeground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={handleChangePassword}
                  disabled={pwBusy}
                  style={[s.editBtn, s.editBtnPrimary, { backgroundColor: c.primary, opacity: pwBusy ? 0.6 : 1 }]}
                >
                  {pwBusy
                    ? <ActivityIndicator size="small" color="#fff" />
                    : <Text style={[s.editBtnText, { color: '#fff' }]}>Update Password</Text>}
                </TouchableOpacity>
              </View>
            </View>
          )}
        </View>

        {/* ── Appearance section ── */}
        <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>Appearance</Text>
        <View style={[s.section, { backgroundColor: c.card, borderColor: c.border }]}>
          <View style={[s.row, { gap: spacing.xs }]}>
            {(['light', 'system', 'dark'] as const).map(opt => {
              const active = activeTheme === opt;
              const label = opt === 'system' ? 'System' : opt === 'dark' ? 'Dark' : 'Light';
              return (
                <TouchableOpacity
                  key={opt}
                  style={[s.themeSegment, {
                    flex: 1,
                    backgroundColor: active ? c.primary : 'transparent',
                    borderColor: active ? c.primary : c.border,
                  }]}
                  onPress={() => pickTheme(opt)}
                  activeOpacity={0.7}
                >
                  <Text style={[s.themeSegmentText, { color: active ? '#fff' : c.mutedForeground }]}>
                    {label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>

        {/* ── Sign out ── */}
        <TouchableOpacity
          style={[s.signOutBtn, { borderColor: c.danger + '40', backgroundColor: c.danger + '08' }]}
          onPress={() => Alert.alert('Sign out', 'Are you sure?', [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Sign out', style: 'destructive', onPress: signOut },
          ])}
          activeOpacity={0.75}
        >
          <Text style={[s.signOutText, { color: c.danger }]}>Sign Out</Text>
        </TouchableOpacity>

        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:        { flex: 1, backgroundColor: c.background },
  header:      { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.xs, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.border },
  title:       { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  content:     { padding: spacing.lg, paddingBottom: 60, gap: spacing.md },

  sectionLabel:{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: -spacing.xs },
  section:     { borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden' },

  row:         { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: spacing.sm + 4, paddingHorizontal: spacing.md },
  rowBorder:   { borderBottomWidth: StyleSheet.hairlineWidth },
  rowLabel:    { fontSize: fontSize.sm },
  rowRight:    { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, flex: 1, justifyContent: 'flex-end' },
  rowValue:    { fontSize: fontSize.sm, fontWeight: fontWeight.medium, flexShrink: 1, marginLeft: spacing.sm },
  editChip:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },

  editBlock:   { padding: spacing.md, gap: spacing.sm },
  editLabel:   { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  editHint:    { fontSize: fontSize.xs, lineHeight: 17 },
  input:       { borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm + 2, fontSize: fontSize.base },
  codeInput:   { textAlign: 'center', fontSize: fontSize.xl, letterSpacing: 8, fontWeight: fontWeight.bold },
  editActions: { flexDirection: 'row', gap: spacing.xs, marginTop: spacing.xs },
  editBtn:     { flex: 1, paddingVertical: spacing.sm + 2, borderRadius: radius.md, borderWidth: 1, alignItems: 'center', justifyContent: 'center' },
  editBtnPrimary: { borderWidth: 0 },
  editBtnText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  pwField:     { gap: spacing.xs },
  pwInputRow:  { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: radius.md, paddingHorizontal: spacing.md },
  pwInput:     { flex: 1, paddingVertical: spacing.sm + 2, fontSize: fontSize.base },
  showHide:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold },
  errorText:   { fontSize: fontSize.xs, color: c.danger, marginTop: 2 },

  themeSegment:     { paddingVertical: spacing.sm, borderRadius: radius.md, borderWidth: 1, alignItems: 'center' },
  themeSegmentText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },

  signOutBtn:  { borderRadius: radius.lg, borderWidth: 1, paddingVertical: spacing.md, alignItems: 'center' },
  signOutText: { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
});
