import React, { useState, useRef } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  KeyboardAvoidingView, Platform,
  ActivityIndicator, ScrollView,
} from 'react-native';
import { useAuth, type AuthChallenge } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { DiscordIcon, GoogleIcon } from '@components/ui/BrandIcons';

export default function LoginScreen() {
  const c = useColors();
  const { signIn, respondToChallenge, signInWithProvider } = useAuth();

  const [username,       setUsername]       = useState('');
  const [password,       setPassword]       = useState('');
  const [showPw,         setShowPw]         = useState(false);
  const [loading,        setLoading]        = useState(false);
  const [federatedLoading, setFederatedLoading] = useState<'Discord' | 'Google' | null>(null);
  const [error,          setError]          = useState<string | null>(null);
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
    try {
      const next = await signIn(username.trim(), password);
      if (next) { setChallenge(next); setAnswer(''); }
    } catch (err: any) {
      setError(err.message ?? 'Sign-in failed. Check your credentials.');
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
      setError(err.message ?? 'That code was not accepted. Try again.');
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
      sub:   'Your account needs a second factor. Set it up on the web app, then sign in here.',
      label: '',
      secure: false,
    },
  };

  const handleFederated = async (provider: 'Discord' | 'Google') => {
    setFederatedLoading(provider);
    setError(null);
    try {
      await signInWithProvider(provider);
    } catch (err: any) {
      setError(err.message ?? 'Sign-in failed. Please try again.');
    } finally {
      setFederatedLoading(null);
    }
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
          <Text style={s.cardTitle}>Sign in</Text>
          <Text style={s.cardSub}>Use the credentials provided by your manager</Text>

          {/* ── Challenge step ──────────────────────────────────
              Replaces the credential fields rather than appearing under them:
              the password is already accepted at this point, and leaving it on
              screen invites the user to retype it when the code is refused. */}
          {challenge ? (
            <>
              <View style={s.fieldGroup}>
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
                    placeholderTextColor={c.mutedForeground}
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
            </>
          ) : (
          <>
          {/* Username */}
          <View style={s.fieldGroup}>
            <Text style={s.label}>Username</Text>
            <TextInput
              style={[s.input, { color: c.foreground, borderColor: error ? c.danger + '80' : c.border }]}
              placeholder="username"
              placeholderTextColor={c.mutedForeground}
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
            <View style={s.labelRow}>
              <Text style={s.label}>Password</Text>
              <TouchableOpacity onPress={() => setShowPw(v => !v)} hitSlop={{ top: 8, bottom: 8, left: 12, right: 4 }}>
                <Text style={[s.showHide, { color: c.brandOutdoor }]}>{showPw ? 'Hide' : 'Show'}</Text>
              </TouchableOpacity>
            </View>
            <TextInput
              ref={pwRef}
              style={[s.input, { color: c.foreground, borderColor: error ? c.danger + '80' : c.border }]}
              // No bullet placeholder: `secureTextEntry` already renders bullets,
              // so a bullet placeholder looks like an already-filled field and the
              // user cannot tell whether they have typed anything (worse in dark).
              placeholderTextColor={c.mutedForeground}
              secureTextEntry={!showPw}
              value={password}
              onChangeText={t => { setPassword(t); setError(null); }}
              onSubmitEditing={handleLogin}
              returnKeyType="go"
            />
          </View>

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
            disabled={loading || !!federatedLoading}
            activeOpacity={0.82}
          >
            {loading
              ? <ActivityIndicator color="#fff" />
              : <Text style={s.btnText}>Sign In</Text>
            }
          </TouchableOpacity>

          {/* ── Divider ─────────────────────────────────────── */}
          <View style={s.dividerRow}>
            <View style={[s.dividerLine, { backgroundColor: c.border }]} />
            <Text style={[s.dividerLabel, { color: c.mutedForeground }]}>or</Text>
            <View style={[s.dividerLine, { backgroundColor: c.border }]} />
          </View>

          {/* ── Federated buttons ───────────────────────────── */}
          <TouchableOpacity
            style={[s.socialBtn, { borderColor: '#5865F2', backgroundColor: c.surfaceMuted, opacity: federatedLoading === 'Discord' ? 0.7 : 1 }]}
            onPress={() => handleFederated('Discord')}
            disabled={loading || !!federatedLoading}
            activeOpacity={0.82}
          >
            {federatedLoading === 'Discord'
              ? <ActivityIndicator color="#fff" style={s.socialIcon} />
              : <View style={s.socialIcon}><DiscordIcon size={20} /></View>
            }
            <Text style={[s.socialBtnText, { color: c.foreground }]}>Continue with Discord</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[s.socialBtn, { borderColor: c.border, backgroundColor: c.surfaceMuted, opacity: federatedLoading === 'Google' ? 0.7 : 1 }]}
            onPress={() => handleFederated('Google')}
            disabled={loading || !!federatedLoading}
            activeOpacity={0.82}
          >
            {federatedLoading === 'Google'
              ? <ActivityIndicator color={c.foreground} style={s.socialIcon} />
              : <View style={s.socialIcon}><GoogleIcon size={20} /></View>
            }
            <Text style={[s.socialBtnText, { color: c.foreground }]}>Continue with Google</Text>
          </TouchableOpacity>
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
  labelRow:   { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: spacing.xs },
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

  // Divider
  dividerRow:  { flexDirection: 'row', alignItems: 'center', marginVertical: spacing.lg },
  dividerLine: { flex: 1, height: 1 },
  dividerLabel: { marginHorizontal: spacing.sm, fontSize: fontSize.xs, textTransform: 'uppercase', letterSpacing: 1 },

  // Social buttons
  socialBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderRadius: radius.md,
    paddingVertical: spacing.sm + 4,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  socialIcon:    { width: 22, height: 22, marginRight: spacing.sm, alignItems: 'center', justifyContent: 'center' },
  socialBtnText: { fontSize: fontSize.base, fontWeight: fontWeight.medium },

  hint: {
    textAlign: 'center',
    fontSize: fontSize.xs,
    lineHeight: 18,
    marginTop: spacing.xl,
    marginBottom: spacing.xl,
    paddingHorizontal: spacing.lg,
  },
});
