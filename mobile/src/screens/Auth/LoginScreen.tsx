import React, { useState, useRef } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform,
  ActivityIndicator, ScrollView,
} from 'react-native';
import { useAuth, type AuthChallenge } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { classifySignInError } from './signInError';
import ResetRequest, { ResetRequestLink, type ResetSent } from './ResetRequest';
import SignInNotice, { NoticeText } from './SignInNotice';
import SetupKey from '@components/SetupKey';

export default function LoginScreen() {
  const c = useColors();
  const { signIn, respondToChallenge, sessionNotice, clearSessionNotice } = useAuth();

  const [username,       setUsername]       = useState('');
  const [password,       setPassword]       = useState('');
  const [showPw,         setShowPw]         = useState(false);
  const [loading,        setLoading]        = useState(false);
  const [error,          setError]          = useState<string | null>(null);
  // ADR-548 D5: the enrolment-window refusal is a state, not an error.
  const [mfaSetupClosed, setMfaSetupClosed] = useState(false);
  /* ADR-556 D3. The reset request is the card while it's open, and on success
     the card returns to sign-in with the username kept and this next step. */
  const [resetOpen, setResetOpen] = useState(false);
  const [resetSent, setResetSent] = useState<ResetSent | null>(null);

  /** Every catch goes through here, so Cognito's trigger wrapper never shows. */
  const fail = (err: any, fallback: string) => {
    const problem = classifySignInError(err?.message, fallback);
    if (problem.kind === 'mfa_setup_closed') setMfaSetupClosed(true);
    else setError(problem.text);
  };
  const pwRef = useRef<TextInput>(null);

  /* ADR-362 — a sign-in can stop on a challenge instead of returning tokens.
     Before this, the context read AuthenticationResult unconditionally and threw
     a TypeError, so even the temporary-password step (which ships today) failed
     with "undefined is not an object" rather than asking for a new password. */
  const [challenge, setChallenge] = useState<AuthChallenge | null>(null);
  const [answer,    setAnswer]    = useState('');

  const handleLogin = async () => {
    if (!username.trim() || !password) {
      setError('Enter your username and password.');
      return;
    }
    setLoading(true);
    setError(null);
    setMfaSetupClosed(false);
    setResetSent(null);
    clearSessionNotice();
    try {
      const next = await signIn(username.trim(), password);
      if (next) { setChallenge(next); setAnswer(''); }
    } catch (err: any) {
      fail(err, 'Sign-in failed. Check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  const handleChallenge = async () => {
    if (!challenge || !answer.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const next = await respondToChallenge(challenge, answer.trim());
      // Cognito chains: choosing a factor returns the challenge for its code.
      setChallenge(next);
      setAnswer('');
    } catch (err: any) {
      fail(err, 'That code was not accepted. Try again.');
    } finally {
      setLoading(false);
    }
  };

  /* Copy per step. A walker reading "SOFTWARE_TOKEN_MFA" learns nothing. */
  const CHALLENGE_COPY: Record<AuthChallenge['name'], { title: string; sub: string; label: string; secure: boolean }> = {
    NEW_PASSWORD_REQUIRED: {
      title: 'Set a new password',
      sub:   'You signed in with a temporary password. Choose a permanent one.',
      label: 'New password',
      secure: true,
    },
    SOFTWARE_TOKEN_MFA: {
      title: 'Enter your code',
      sub:   'Open your authenticator app and enter the 6-digit code.',
      label: 'Authentication code',
      secure: false,
    },
    EMAIL_OTP: {
      title: 'Check your email',
      sub:   challenge?.destination
        ? `We sent a code to ${challenge.destination}.`
        : 'We sent you a sign-in code.',
      label: 'Emailed code',
      secure: false,
    },
    SELECT_MFA_TYPE: {
      title: 'Choose a method',
      sub:   'Pick how you want to confirm it is you.',
      label: 'Method',
      secure: false,
    },
    MFA_SETUP: {
      title: 'Set up sign-in security',
      sub:   'Add this key to your authenticator app, then enter the code it shows.',
      label: 'Code from your app',
      secure: false,
    },
  };

  const s = styles(c);

  return (
    <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={s.container} keyboardShouldPersistTaps="handled" bounces={false}>

        {/* ── Top brand block ─────────────────────────────────── */}
        <View style={s.hero}>
          <View style={s.logoRing}>
            <View style={s.logoInner}>
              <Text style={s.logoLetters}>AF</Text>
            </View>
          </View>
          <Text style={s.brandName}>AsheFlow</Text>
          <Text style={s.brandTagline}>Field operations, simplified</Text>
        </View>

        {/* ── Form card ───────────────────────────────────────── */}
        <View style={s.card}>
          <Text style={s.cardTitle}>{resetOpen ? 'Request a two-factor reset' : 'Sign in'}</Text>
          <Text style={s.cardSub}>
            {resetOpen ? "For when you can't use your authenticator" : 'Use the credentials provided by your manager'}
          </Text>

          {resetOpen ? (
            <ResetRequest
              username={username.trim()}
              onCancel={() => setResetOpen(false)}
              onSent={result => {
                // Back to the username/password form; the username stays.
                setResetOpen(false);
                setChallenge(null);
                setAnswer('');
                setPassword('');
                setError(null);
                setMfaSetupClosed(false);
                setResetSent(result);
                clearSessionNotice();
              }}
            />
          ) : (
          <>

          {/* ── Challenge step ──────────────────────────────────
              Replaces the credential fields rather than appearing under them:
              the password is already accepted at this point, and leaving it on
              screen invites the user to retype it when the code is refused. */}
          {challenge ? (
            <>
              <View style={s.fieldGroup}>
                {/* No QR code, deliberately: this device IS the one holding the
                    authenticator, so it can't scan its own screen. ADR-557: the
                    key opens in the app or is copied, never retyped. Shown
                    BEFORE the code field: there's no code until it's added. */}
                {challenge.name === 'MFA_SETUP' && challenge.totpSecret ? (
                  <View style={{ marginBottom: spacing.md }}>
                    <SetupKey secret={challenge.totpSecret} account={username.trim()} />
                  </View>
                ) : null}
                <Text style={s.label}>{CHALLENGE_COPY[challenge.name].label}</Text>
                {challenge.name === 'SELECT_MFA_TYPE' ? (
                  <View>
                    {(challenge.options ?? []).map(opt => (
                      <TouchableOpacity
                        key={opt}
                        style={[s.input, { justifyContent: 'center', borderColor: c.border }]}
                        onPress={() => { setAnswer(opt); }}
                      >
                        <Text style={{ color: answer === opt ? c.brand : c.foreground }}>
                          {opt === 'SOFTWARE_TOKEN_MFA' ? 'Authenticator app' : 'Emailed code'}
                        </Text>
                      </TouchableOpacity>
                    ))}
                  </View>
                ) : (
                  <TextInput
                    style={[s.input, { color: c.foreground, borderColor: error ? c.danger + '80' : c.border }]}
                    placeholderTextColor={c.placeholder}
                    // A 6-digit code on a numeric pad, not a full keyboard: this
                    // is typed in a van, one-handed.
                    keyboardType={challenge.name === 'NEW_PASSWORD_REQUIRED' ? 'default' : 'number-pad'}
                    textContentType={challenge.name === 'NEW_PASSWORD_REQUIRED' ? 'newPassword' : 'oneTimeCode'}
                    autoComplete={challenge.name === 'NEW_PASSWORD_REQUIRED' ? 'password-new' : 'one-time-code'}
                    secureTextEntry={CHALLENGE_COPY[challenge.name].secure}
                    autoCapitalize="none"
                    autoFocus
                    value={answer}
                    onChangeText={t => { setAnswer(t); setError(null); }}
                    onSubmitEditing={handleChallenge}
                    returnKeyType="go"
                  />
                )}
              </View>

              {error && (
                <View style={[s.errorBox, { backgroundColor: c.danger + '0D', borderColor: c.danger + '30' }]}>
                  <Text style={[s.errorText, { color: c.danger }]}>{error}</Text>
                </View>
              )}

              <TouchableOpacity
                style={[s.btn, { backgroundColor: c.brand, opacity: loading || !answer.trim() ? 0.7 : 1 }]}
                onPress={handleChallenge}
                disabled={loading || !answer.trim()}
              >
                <Text style={s.btnText}>{loading ? 'Checking…' : 'Continue'}</Text>
              </TouchableOpacity>

              <TouchableOpacity
                onPress={() => { setChallenge(null); setAnswer(''); setError(null); setPassword(''); }}
                style={{ marginTop: spacing.md, alignItems: 'center' }}
              >
                <Text style={[s.showHide, { color: c.mutedForeground }]}>Start over</Text>
              </TouchableOpacity>

              {/* ADR-551 D1: the way out for someone who can't produce the code. */}
              {(challenge.name === 'SOFTWARE_TOKEN_MFA' || challenge.name === 'EMAIL_OTP') &&
                <ResetRequestLink onPress={() => { setError(null); setResetOpen(true); }} />}
            </>
          ) : (
          <>
          {/* ADR-556 D3: what happens next, after a reset request. */}
          {resetSent && (
            <SignInNotice tone="success" title={`Request sent to ${resetSent.sentTo}`}>
              {resetSent.nextStep}
            </SignInNotice>
          )}
          {/* ADR-556 D5: why this device was signed out. One stamp ends sessions
              for a password change, an email change AND a two-factor reset, so
              the wording names all three; who to contact depends on the account. */}
          {sessionNotice && !resetSent && !mfaSetupClosed && (
            <SignInNotice tone="warning" title="You were signed out on every device">
              <NoticeText>
                This account's password, email or two-factor sign-in was changed. Sign in again to continue.
              </NoticeText>
              <NoticeText strong="Didn't expect this?">
                {sessionNotice.audience === 'platform'
                  ? 'Contact AsheFlow support straight away.'
                  : 'Tell your manager straight away.'}
              </NoticeText>
            </SignInNotice>
          )}
          {/* Username */}
          <View style={s.fieldGroup}>
            <Text style={s.label}>Username</Text>
            <TextInput
              style={[s.input, { color: c.foreground, borderColor: error ? c.danger + '80' : c.border }]}
              placeholder="username"
              placeholderTextColor={c.placeholder}
              autoCapitalize="none"
              autoCorrect={false}
              value={username}
              onChangeText={t => { setUsername(t); setError(null); }}
              returnKeyType="next"
              onSubmitEditing={() => pwRef.current?.focus()}
              blurOnSubmit={false}
            />
          </View>

          {/* Password */}
          <View style={s.fieldGroup}>
            <Text style={s.label}>Password</Text>
            <TextInput
              ref={pwRef}
              style={[s.input, { color: c.foreground, borderColor: error ? c.danger + '80' : c.border }]}
              // No bullet placeholder: `secureTextEntry` already renders bullets,
              // so a bullet placeholder looks like an already-filled field and the
              // user cannot tell whether they have typed anything (worse in dark).
              placeholderTextColor={c.placeholder}
              secureTextEntry={!showPw}
              value={password}
              onChangeText={t => { setPassword(t); setError(null); }}
              onSubmitEditing={handleLogin}
              returnKeyType="go"
            />
            {/* Under the field, not beside its label (owner, 2026-10-21): focus
                then runs username -> password -> toggle, the order the eye reads
                and the order a hardware Tab key walks. */}
            <TouchableOpacity
              onPress={() => setShowPw(v => !v)}
              style={s.showRow}
              hitSlop={{ top: 8, bottom: 8, left: 12, right: 4 }}
              accessibilityRole="switch"
              accessibilityState={{ checked: showPw }}
              accessibilityLabel="Show password"
            >
              <Text style={[s.showHide, { color: c.brandOutdoor }]}>{showPw ? 'Hide password' : 'Show password'}</Text>
            </TouchableOpacity>
          </View>

          {/* ADR-548 D5. Warning, not danger: nothing the person typed was
              wrong, and there is one way out. What happened, then what to do. */}
          {mfaSetupClosed && (
            <SignInNotice tone="warning" title="Two-factor setup needed">
              <NoticeText>
                This account needs two-factor authentication, and the 24 hours to
                set it up after your first sign-in have passed.
              </NoticeText>
              <NoticeText strong="What to do:">
                request a reset below. Once someone resets it, sign in again and
                you will go straight to setup.
              </NoticeText>
            </SignInNotice>
          )}
          {/* ADR-551 D1: and for someone whose setup window closed. */}
          {mfaSetupClosed && <ResetRequestLink onPress={() => setResetOpen(true)} />}

          {/* Error */}
          {error && (
            <View style={[s.errorBox, { backgroundColor: c.danger + '0D', borderColor: c.danger + '30' }]}>
              <Text style={[s.errorText, { color: c.danger }]}>{error}</Text>
            </View>
          )}

          {/* Submit */}
          <TouchableOpacity
            style={[s.btn, { backgroundColor: c.brand, opacity: loading ? 0.7 : 1 }]}
            onPress={handleLogin}
            disabled={loading}
            activeOpacity={0.82}
          >
            {loading
              ? <ActivityIndicator color="#fff" />
              : <Text style={s.btnText}>Sign In</Text>
            }
          </TouchableOpacity>

          </>
          )}
          </>
          )}
        </View>

        {/* ── Footer note ─────────────────────────────────────── */}
        <Text style={[s.hint, { color: c.mutedForeground }]}>
          Accounts are managed by your dispatcher.{'\n'}
          <Text style={{ color: c.foreground, fontWeight: fontWeight.semibold }}>No self-signup.</Text>
        </Text>

      </ScrollView>
    </KeyboardAvoidingView>
  );
}


const styles = (c: ThemeColors) => StyleSheet.create({
  flex:       { flex: 1, backgroundColor: c.background },
  container:  { flexGrow: 1, alignItems: 'stretch' },

  // Hero
  hero: {
    // brandSurface: a deep navy that is CONSTANT across themes.
    //
    // This was c.primary (the lifted #7E95F1 in dark), then primaryStrong —
    // both wrong. `primaryStrong` means "more prominent than primary", which
    // on a dark theme means LIGHTER (#A1B2F7), so the hero stayed periwinkle.
    // The hero is brand furniture, like a marketing header: it should not flip
    // with the theme at all.
    backgroundColor: c.brandSurface,
    alignItems: 'center',
    paddingTop: 80,
    paddingBottom: 48,
    paddingHorizontal: spacing.lg,
  },
  logoRing: {
    width: 72, height: 72, borderRadius: 36,
    backgroundColor: 'rgba(255,255,255,0.2)',
    alignItems: 'center', justifyContent: 'center',
    marginBottom: spacing.md,
  },
  logoInner: {
    // Constant light disc. c.surface was WRONG: it is white in light theme but
    // dark navy in dark theme, which dropped the navy letters on it to 1.12:1.
    // The disc sits on the theme-constant hero, so it must be constant too —
    // brandSurfaceForeground is white in both.
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: c.brandSurfaceForeground,
    alignItems: 'center', justifyContent: 'center',
  },
  logoLetters:  { fontSize: fontSize.md, fontWeight: fontWeight.extrabold, color: c.brandSurface, letterSpacing: 0.5 },
  brandName:    { fontSize: fontSize['2xl'], fontWeight: fontWeight.extrabold, color: c.brandSurfaceForeground, letterSpacing: -0.5 },
  brandTagline: { fontSize: fontSize.sm, color: c.brandSurfaceForeground, opacity: 0.78, marginTop: 4, fontWeight: fontWeight.medium },

  // Card
  card: {
    backgroundColor: c.card,
    marginHorizontal: spacing.lg,
    marginTop: -20,
    borderRadius: radius.xl,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: c.border,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 12,
    elevation: 4,
  },
  cardTitle:  { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.foreground, marginBottom: 4 },
  cardSub:    { fontSize: fontSize.xs, color: c.mutedForeground, marginBottom: spacing.lg },

  fieldGroup: { marginBottom: spacing.md },
  showRow:    { alignSelf: 'flex-end', marginTop: spacing.xs, paddingVertical: 2 },
  label:      { fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.foreground },
  // brandOutdoor, not brand: `brand` is tuned against the BACKGROUND and only
  // reaches 4.10:1 on the lighter card, short of the 4.5 this small text needs.
  showHide:   { fontSize: fontSize.sm, fontWeight: fontWeight.medium },
  input: {
    backgroundColor: c.surfaceMuted,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 4,
    fontSize: fontSize.base,
  },

  errorBox:  { borderRadius: radius.md, borderWidth: 1, padding: spacing.sm + 2, marginBottom: spacing.sm },
  errorText: { fontSize: fontSize.sm, fontWeight: fontWeight.medium },

  btn: {
    marginTop: spacing.xs,
    borderRadius: radius.md,
    paddingVertical: spacing.sm + 6,
    alignItems: 'center',
  },
  btnText: { color: c.brandForeground, fontSize: fontSize.base, fontWeight: fontWeight.semibold, letterSpacing: 0.2 },

  hint: {
    textAlign: 'center',
    fontSize: fontSize.xs,
    lineHeight: 18,
    marginTop: spacing.xl,
    marginBottom: spacing.xl,
    paddingHorizontal: spacing.lg,
  },
});
