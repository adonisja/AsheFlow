/**
 * Account settings — credentials and appearance.
 *
 * Split out of the former MyAccountScreen (452 lines), which mixed settings with
 * two different performance surfaces. The split is by WHO SAYS IT:
 *   Settings   this file — the user's own credentials and preferences
 *   My Stats   AsheFlow's record of their work (/field-ops/me/performance)
 *   Scorecard  Amazon's weekly assessment (/scorecards/me/trend)
 *
 * Merging the latter two would recreate the ambiguity that made "what is the
 * difference between these cards?" a reasonable question — they are independent
 * sources that can legitimately disagree.
 *
 * Renders inside the MyAccountScreen tab shell, so no PageHeader/SafeAreaView here.
 */
import React, { useEffect, useState } from 'react';
import { errorText } from '@api/errorText';
import {
  View, Text, StyleSheet, TouchableOpacity,
  ScrollView, TextInput, Alert, ActivityIndicator,
} from 'react-native';
import { useAuth } from '@contexts/AuthContext';
import { useColors, useTheme } from '@contexts/ThemeContext';
import apiClient from '@api/client';
import MfaEnrolment from '@components/MfaEnrolment';
import SignInNameCard from '@components/SignInNameCard';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type EmailStep    = 'idle' | 'entering' | 'verifying';
/** Same three states as email: the Discord flow is deliberately identical, so
 *  a user who has changed their email already knows how this works. */
type DiscordStep  = 'idle' | 'entering' | 'verifying';
type PasswordStep = 'idle' | 'code';

export default function AccountSettingsScreen() {
  const c = useColors();
  const { isDark, isSystemTheme, setTheme } = useTheme();
  const { user, signOut, mfaStatus, refreshMfaStatus } = useAuth();
  const s = styles(c);

  // Email edit
  const [emailStep,    setEmailStep]    = useState<EmailStep>('idle');
  const [newEmail,     setNewEmail]     = useState('');
  const [currentCode,  setCurrentCode]  = useState('');
  const [newCode,      setNewCode]      = useState('');
  const [masked,       setMasked]       = useState<{ current: string; new: string } | null>(null);
  const [emailBusy,    setEmailBusy]    = useState(false);
  const [currentEmail, setCurrentEmail] = useState(user?.email ?? '');

  // ADR-566 D4. Hidden until the environment's pool accepts sign-in names.
  const [signInName, setSignInName] = useState<
    { available: boolean; username: string; sign_in_name: string | null } | null>(null);
  useEffect(() => {
    apiClient.get('/employees/me/sign-in-name')
      .then(r => setSignInName(r.data))
      .catch(() => { /* silent: the section just stays hidden */ });
  }, []);

  // Discord link (ADR-270)
  const [dStep,    setDStep]    = useState<DiscordStep>('idle');
  const [dId,      setDId]      = useState('');
  const [dCode,    setDCode]    = useState('');
  const [dBusy,    setDBusy]    = useState(false);
  const [dHelp,    setDHelp]    = useState(false);
  const [currentDiscord, setCurrentDiscord] = useState<string | null>(
    (user as any)?.discord_id ?? null,
  );

  // Password change
  const [pwStep,     setPwStep]     = useState<PasswordStep>('idle');
  const [pwCode,     setPwCode]     = useState('');
  const [pwSentTo,   setPwSentTo]   = useState('');
  const [newPw,      setNewPw]      = useState('');
  const [confirmPw,  setConfirmPw]  = useState('');
  const [showNew,     setShowNew]     = useState(false);
  const [pwBusy,     setPwBusy]     = useState(false);

  // ── Credential changes (ADR-541) ────────────────────────────────────────────
  // Both are confirmed by codes sent to the person's inbox, and both END EVERY
  // SESSION on success -- this one included -- so the app signs out and says why.
  // Neither calls Cognito directly any more: the server makes the change.

  const leaveAfterChange = (title: string, body: string) => {
    Alert.alert(title, body, [{ text: 'Sign in again', onPress: signOut }], { cancelable: false });
  };

  // ── Email handlers ──────────────────────────────────────────────────────────

  const requestEmailChange = async () => {
    if (!newEmail.trim() || !newEmail.includes('@')) {
      Alert.alert('Invalid email', 'Enter a valid email address.');
      return;
    }
    setEmailBusy(true);
    try {
      const res = await apiClient.post<{ current_masked: string; new_masked: string }>(
        '/employees/me/email/request-change', { new_email: newEmail.trim().toLowerCase() },
      );
      setMasked({ current: res.data.current_masked, new: res.data.new_masked });
      setEmailStep('verifying');
    } catch (e: any) {
      Alert.alert('Could not send codes', errorText(e, 'Please try again.'));
    } finally {
      setEmailBusy(false);
    }
  };

  const confirmEmailChange = async () => {
    if (currentCode.trim().length < 6 || newCode.trim().length < 6) {
      Alert.alert('Codes needed', 'Enter both 6-digit codes.');
      return;
    }
    setEmailBusy(true);
    try {
      await apiClient.post('/employees/me/email/confirm-change', {
        current_code: currentCode.trim(),
        new_code: newCode.trim(),
      });
      setCurrentEmail(newEmail.trim().toLowerCase());
      leaveAfterChange('Email updated', 'You were signed out everywhere. Sign in again to continue.');
    } catch (e: any) {
      Alert.alert('Could not verify', errorText(e, 'Please try again.'));
    } finally {
      setEmailBusy(false);
    }
  };

  const cancelEmail = () => {
    setEmailStep('idle'); setNewEmail(''); setCurrentCode(''); setNewCode(''); setMasked(null);
  };

  // ── Discord handlers ────────────────────────────────────────────────────────

  const requestDiscordLink = async () => {
    // Mirror the server's ADR-083 rule locally so a typo is caught before it
    // DMs a stranger, not after.
    if (!/^[0-9]{17,20}$/.test(dId.trim())) {
      Alert.alert('Invalid Discord ID', 'A Discord ID is 17-20 digits. See "How do I find this?" below.');
      return;
    }
    setDBusy(true);
    try {
      await apiClient.post('/employees/me/discord/request-link', {
        discord_id: dId.trim(),
      });
      setDStep('verifying');
    } catch (e: any) {
      const status = e?.response?.status;
      Alert.alert(
        status === 409 ? 'Already linked' : status === 429 ? 'Too many attempts' : 'Could not send code',
        e?.response?.data?.detail ?? 'Please try again.',
      );
    } finally {
      setDBusy(false);
    }
  };

  const confirmDiscordLink = async () => {
    if (dCode.trim().length !== 6) {
      Alert.alert('Invalid code', 'Enter the 6-digit code sent to your Discord DMs.');
      return;
    }
    setDBusy(true);
    try {
      const res = await apiClient.post('/employees/me/discord/confirm-link', {
        discord_id: dId.trim(),
        code: dCode.trim(),
      });
      setCurrentDiscord(res.data?.discord_id ?? dId.trim());
      setDStep('idle');
      setDId(''); setDCode('');
      Alert.alert('Linked', 'Your Discord account is now linked.');
    } catch (e: any) {
      Alert.alert('Could not link', e?.response?.data?.detail ?? 'Please try again.');
    } finally {
      setDBusy(false);
    }
  };

  const cancelDiscord = () => { setDStep('idle'); setDId(''); setDCode(''); setDHelp(false); };

  // ── Password handlers ───────────────────────────────────────────────────────

  const requestPasswordCode = async () => {
    setPwBusy(true);
    try {
      const res = await apiClient.post<{ sent_to: string }>('/employees/me/password/request-code');
      setPwSentTo(res.data.sent_to);
      setPwStep('code');
    } catch (e: any) {
      Alert.alert('Could not send code', errorText(e, 'Please try again.'));
    } finally {
      setPwBusy(false);
    }
  };

  const handleChangePassword = async () => {
    if (pwCode.trim().length < 6) {
      Alert.alert('Code needed', 'Enter the 6-digit code from the email.');
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
      await apiClient.post('/employees/me/password/confirm', { code: pwCode.trim(), new_password: newPw });
      leaveAfterChange('Password changed', 'You were signed out everywhere. Sign in with your new password.');
    } catch (e: any) {
      Alert.alert('Could not change password', errorText(e, 'Please try again.'));
    } finally {
      setPwBusy(false);
    }
  };

  const cancelPassword = () => {
    setPwStep('idle');
    setPwCode(''); setNewPw(''); setConfirmPw('');
    setShowNew(false);
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
    <View style={s.safe}>

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
          {/* ADR-541 R3: a first email is added by an admin -- with no current
              address there is nothing to confirm the change against. */}
          {emailStep === 'idle' && (
            <TouchableOpacity
              style={s.row}
              onPress={() => {
                if (!currentEmail) {
                  Alert.alert('Add your email', 'Ask your manager or an admin to add your email address from the People page.');
                  return;
                }
                setNewEmail(''); setEmailStep('entering');
              }}
              activeOpacity={0.7}
            >
              <Text style={[s.rowLabel, { color: c.mutedForeground }]}>Email</Text>
              <View style={s.rowRight}>
                <Text style={[s.rowValue, { color: c.foreground }]} numberOfLines={1}>{currentEmail || '—'}</Text>
                <Text style={[s.editChip, { color: c.primary }]}>{currentEmail ? 'Change' : 'Add'}</Text>
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
                placeholderTextColor={c.placeholder}
                keyboardType="email-address"
                autoCapitalize="none"
                autoCorrect={false}
                autoFocus
              />
              <Text style={[s.editHint, { color: c.mutedForeground }]}>
                We'll email a code to your current address and one to the new address.
                After the change you'll be signed out everywhere.
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
                    ? <ActivityIndicator size="small" color={c.primaryForeground} />
                    : <Text style={[s.editBtnText, { color: c.primaryForeground }]}>Send Code</Text>}
                </TouchableOpacity>
              </View>
            </View>
          )}

          {emailStep === 'verifying' && (
            <View style={s.editBlock}>
              <Text style={[s.editLabel, { color: c.foreground }]}>
                Code sent to {masked?.current ?? 'your current email'}
              </Text>
              <TextInput
                style={[s.input, s.codeInput, { color: c.foreground, borderColor: c.border, backgroundColor: c.surfaceMuted }]}
                value={currentCode}
                onChangeText={setCurrentCode}
                placeholder="000000"
                placeholderTextColor={c.placeholder}
                keyboardType="number-pad"
                textContentType="oneTimeCode"
                maxLength={6}
                autoFocus
              />
              <Text style={[s.editLabel, { color: c.foreground }]}>
                Code sent to {masked?.new ?? 'the new email'}
              </Text>
              <TextInput
                style={[s.input, s.codeInput, { color: c.foreground, borderColor: c.border, backgroundColor: c.surfaceMuted }]}
                value={newCode}
                onChangeText={setNewCode}
                placeholder="000000"
                placeholderTextColor={c.placeholder}
                keyboardType="number-pad"
                maxLength={6}
              />
              <Text style={[s.editHint, { color: c.mutedForeground }]}>Codes expire in 10 minutes.</Text>
              <View style={s.editActions}>
                <TouchableOpacity onPress={cancelEmail} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.mutedForeground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={() => { setEmailStep('entering'); setCurrentCode(''); setNewCode(''); }} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.primary }]}>Resend</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={confirmEmailChange}
                  disabled={emailBusy || currentCode.length < 6 || newCode.length < 6}
                  style={[s.editBtn, s.editBtnPrimary, { backgroundColor: c.primary, opacity: (emailBusy || currentCode.length < 6 || newCode.length < 6) ? 0.5 : 1 }]}
                >
                  {emailBusy
                    ? <ActivityIndicator size="small" color={c.primaryForeground} />
                    : <Text style={[s.editBtnText, { color: c.primaryForeground }]}>Confirm</Text>}
                </TouchableOpacity>
              </View>
            </View>
          )}

          {/* ── Discord row (ADR-270) ──
              Verified, not a free edit: discord_id is the bot's DM address and
              the third step of the auth lookup chain, so the flow mirrors email
              exactly — send a code to the claimed account, prove receipt, write. */}
          {dStep === 'idle' && (
            <TouchableOpacity
              style={[s.row, s.rowBorder, { borderTopColor: c.border, borderTopWidth: 1, borderBottomWidth: 0 }]}
              onPress={() => { setDId(currentDiscord ?? ''); setDStep('entering'); }}
              activeOpacity={0.7}
            >
              <Text style={[s.rowLabel, { color: c.mutedForeground }]}>Discord</Text>
              <View style={s.rowRight}>
                <Text style={[s.rowValue, { color: currentDiscord ? c.foreground : c.mutedForeground }]}
                      numberOfLines={1}>
                  {currentDiscord ?? 'Not linked'}
                </Text>
                <Text style={[s.editChip, { color: c.primary }]}>
                  {currentDiscord ? 'Change' : 'Link'}
                </Text>
              </View>
            </TouchableOpacity>
          )}

          {dStep === 'entering' && (
            <View style={s.editBlock}>
              <Text style={[s.editLabel, { color: c.foreground }]}>Discord ID</Text>
              <TextInput
                style={[s.input, { color: c.foreground, borderColor: c.border, backgroundColor: c.surfaceMuted }]}
                value={dId}
                onChangeText={setDId}
                placeholder="219476523456789012"
                placeholderTextColor={c.placeholder}
                keyboardType="number-pad"
                autoCorrect={false}
                autoFocus
              />
              <Text style={[s.editHint, { color: c.mutedForeground }]}>
                We'll DM a 6-digit code to that Discord account to confirm it's yours.
              </Text>

              {/* The steps inline rather than a link out: nobody knows their own
                  snowflake, and Developer Mode is off by default. */}
              <TouchableOpacity onPress={() => setDHelp(h => !h)}>
                <Text style={[s.editHint, { color: c.primary }]}>
                  {dHelp ? '▾' : '▸'} How do I find this?
                </Text>
              </TouchableOpacity>
              {dHelp && (
                <View style={s.helpBlock}>
                  {[
                    'Open Discord → Settings (gear icon)',
                    'Advanced → turn on Developer Mode',
                    'Tap your own name or avatar',
                    'Tap the ⋯ menu → Copy User ID',
                  ].map((line, i) => (
                    <Text key={i} style={[s.helpLine, { color: c.mutedForeground }]}>
                      {i + 1}. {line}
                    </Text>
                  ))}
                  <Text style={[s.helpLine, { color: c.mutedForeground }]}>
                    It's a 17–20 digit number — not your username.
                  </Text>
                </View>
              )}

              <View style={s.editActions}>
                <TouchableOpacity onPress={cancelDiscord} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.mutedForeground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={requestDiscordLink}
                  disabled={dBusy}
                  style={[s.editBtn, s.editBtnPrimary, { backgroundColor: c.primary, opacity: dBusy ? 0.6 : 1 }]}
                >
                  {dBusy
                    ? <ActivityIndicator size="small" color={c.primaryForeground} />
                    : <Text style={[s.editBtnText, { color: c.primaryForeground }]}>Send Code</Text>}
                </TouchableOpacity>
              </View>
            </View>
          )}

          {dStep === 'verifying' && (
            <View style={s.editBlock}>
              <Text style={[s.editLabel, { color: c.foreground }]}>Verification code</Text>
              <Text style={[s.editHint, { color: c.mutedForeground }]}>
                Check your Discord DMs for a 6-digit code from the AsheFlow bot.
              </Text>
              <TextInput
                style={[s.input, s.codeInput, { color: c.foreground, borderColor: c.border, backgroundColor: c.surfaceMuted }]}
                value={dCode}
                onChangeText={setDCode}
                placeholder="000000"
                placeholderTextColor={c.placeholder}
                keyboardType="number-pad"
                maxLength={6}
                autoFocus
              />
              <View style={s.editActions}>
                <TouchableOpacity onPress={cancelDiscord} style={[s.editBtn, { borderColor: c.border }]}>
                  <Text style={[s.editBtnText, { color: c.mutedForeground }]}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={confirmDiscordLink}
                  disabled={dBusy || dCode.length < 6}
                  style={[s.editBtn, s.editBtnPrimary, { backgroundColor: c.primary, opacity: (dBusy || dCode.length < 6) ? 0.5 : 1 }]}
                >
                  {dBusy
                    ? <ActivityIndicator size="small" color={c.primaryForeground} />
                    : <Text style={[s.editBtnText, { color: c.primaryForeground }]}>Confirm</Text>}
                </TouchableOpacity>
              </View>
            </View>
          )}
        </View>

        {/* ── Sign-in name (ADR-566 D4) ── */}
        {signInName?.available && (
          <View style={[s.section, s.signInName, { backgroundColor: c.card, borderColor: c.border }]}>
            <SignInNameCard path="/employees/me/sign-in-name" current={signInName.sign_in_name}
                            username={signInName.username} />
          </View>
        )}

        {/* ── Security section ── */}
        <Text style={[s.sectionLabel, { color: c.mutedForeground }]}>Security</Text>
        <View style={[s.section, { backgroundColor: c.card, borderColor: c.border }]}>

          {pwStep === 'idle' ? (
            <TouchableOpacity
              style={s.row}
              onPress={() => {
                if (!currentEmail) {
                  Alert.alert('Email needed', 'Changing your password needs an email address to send a code to. Ask your manager or an admin to add it.');
                  return;
                }
                Alert.alert(
                  'Change password',
                  "We'll email you a code. After the change you'll be signed out everywhere, including this phone.",
                  [{ text: 'Cancel', style: 'cancel' }, { text: 'Email me a code', onPress: requestPasswordCode }],
                );
              }}
              activeOpacity={0.7}
              disabled={pwBusy}
            >
              <Text style={[s.rowLabel, { color: c.mutedForeground }]}>Password</Text>
              <View style={s.rowRight}>
                <Text style={[s.rowValue, { color: c.foreground }]}>••••••••</Text>
                <Text style={[s.editChip, { color: c.primary }]}>Change</Text>
              </View>
            </TouchableOpacity>
          ) : (
            <View style={s.editBlock}>
              {/* Code from the email (ADR-541 D1) */}
              <View style={s.pwField}>
                <Text style={[s.editLabel, { color: c.foreground }]}>Code sent to {pwSentTo}</Text>
                <TextInput
                  style={[s.input, s.codeInput, { color: c.foreground, borderColor: c.border, backgroundColor: c.surfaceMuted }]}
                  value={pwCode}
                  onChangeText={setPwCode}
                  placeholder="000000"
                  placeholderTextColor={c.placeholder}
                  keyboardType="number-pad"
                  textContentType="oneTimeCode"
                  maxLength={6}
                  autoFocus
                />
              </View>

              {/* New password */}
              <View style={s.pwField}>
                <Text style={[s.editLabel, { color: c.foreground }]}>New password</Text>
                <View style={[s.pwInputRow, { borderColor: c.border, backgroundColor: c.surfaceMuted }]}>
                  <TextInput
                    style={[s.pwInput, { color: c.foreground }]}
                    secureTextEntry={!showNew}
                    placeholder="At least 8 characters"
                    placeholderTextColor={c.placeholder}
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
                    placeholderTextColor={c.placeholder}
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
                    ? <ActivityIndicator size="small" color={c.primaryForeground} />
                    : <Text style={[s.editBtnText, { color: c.primaryForeground }]}>Change password</Text>}
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
                  <Text style={[s.themeSegmentText, { color: active ? c.primaryForeground : c.mutedForeground }]}>
                    {label}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </View>
        </View>

        {/* ── Two-factor (ADR-381 D2) ──
            The counting-down surface. The BLOCKED case never reaches here --
            RootNavigator swaps this whole shell out for MfaRequiredScreen -- so
            this is only ever the warning, and it is a section rather than a
            banner because a banner on a phone is one swipe from gone. */}
        {mfaStatus && mfaStatus.required && mfaStatus.enrolled === false && (
          <View style={s.section}>
            <Text style={s.sectionLabel}>Two-factor authentication</Text>
            <Text style={s.editHint}>
              {mfaStatus.days_remaining === 1
                ? 'Required from tomorrow.'
                : `Required in ${mfaStatus.days_remaining} days.`}
            </Text>
            <MfaEnrolment onEnrolled={refreshMfaStatus} />
          </View>
        )}
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
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  safe:        { flex: 1, backgroundColor: c.background },
  header:      { paddingHorizontal: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing.xs, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: c.border },
  title:       { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground },
  content:     { padding: spacing.lg, paddingBottom: 60, gap: spacing.md },

  sectionLabel:{ fontSize: fontSize.xs, fontWeight: fontWeight.semibold, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: -spacing.xs },
  section:     { borderRadius: radius.lg, borderWidth: 1, overflow: 'hidden' },
  signInName:  { padding: spacing.md, marginTop: spacing.lg },

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
  helpBlock:   { marginTop: 4, marginLeft: spacing.xs, gap: 2 },
  helpLine:    { fontSize: 11, lineHeight: 16 },
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
