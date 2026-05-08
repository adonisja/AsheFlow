import React, { useState, useRef } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  useColorScheme, KeyboardAvoidingView, Platform,
  ActivityIndicator, ScrollView,
} from 'react-native';
import { useAuth } from '@contexts/AuthContext';
import { lightColors, darkColors, spacing, radius, fontSize, fontWeight } from '@theme/index';

export default function LoginScreen() {
  const scheme = useColorScheme();
  const c = scheme === 'dark' ? darkColors : lightColors;
  const { signIn } = useAuth();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPw,   setShowPw]   = useState(false);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const pwRef = useRef<TextInput>(null);

  const handleLogin = async () => {
    if (!username.trim() || !password) {
      setError('Enter your username and password.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await signIn(username.trim(), password);
    } catch (err: any) {
      setError(err.message ?? 'Sign-in failed. Check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  const s = styles(c);

  return (
    <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={s.container} keyboardShouldPersistTaps="handled" bounces={false}>

        {/* ── Top brand block ─────────────────────────────────── */}
        <View style={s.hero}>
          {/* Logo mark */}
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

          {/* Username */}
          <View style={s.fieldGroup}>
            <Text style={s.label}>Username</Text>
            <TextInput
              style={[s.input, { color: c.foreground, borderColor: error ? c.danger + '80' : c.border }]}
              placeholder="username or email"
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
                <Text style={[s.showHide, { color: c.primary }]}>{showPw ? 'Hide' : 'Show'}</Text>
              </TouchableOpacity>
            </View>
            <TextInput
              ref={pwRef}
              style={[s.input, { color: c.foreground, borderColor: error ? c.danger + '80' : c.border }]}
              placeholder="••••••••••••"
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
            style={[s.btn, { backgroundColor: c.primary, opacity: loading ? 0.7 : 1 }]}
            onPress={handleLogin}
            disabled={loading}
            activeOpacity={0.82}
          >
            {loading
              ? <ActivityIndicator color="#fff" />
              : <Text style={s.btnText}>Sign In</Text>
            }
          </TouchableOpacity>
        </View>

        {/* ── Footer note ─────────────────────────────────────── */}
        <Text style={[s.hint, { color: c.mutedForeground }]}>
          Accounts are managed by your manager.{'\n'}Contact your supervisor if you need access.
        </Text>

      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = (c: typeof lightColors) => StyleSheet.create({
  flex:       { flex: 1, backgroundColor: c.background },
  container:  { flexGrow: 1, alignItems: 'stretch' },

  // Hero
  hero: {
    backgroundColor: c.primary,
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
    width: 56, height: 56, borderRadius: 28,
    backgroundColor: '#fff',
    alignItems: 'center', justifyContent: 'center',
  },
  logoLetters:  { fontSize: fontSize.md, fontWeight: fontWeight.extrabold, color: c.primary, letterSpacing: 0.5 },
  brandName:    { fontSize: fontSize.xxl, fontWeight: fontWeight.extrabold, color: '#fff', letterSpacing: -0.5 },
  brandTagline: { fontSize: fontSize.sm, color: 'rgba(255,255,255,0.72)', marginTop: 4, fontWeight: fontWeight.medium },

  // Card
  card: {
    backgroundColor: c.card,
    marginHorizontal: spacing.lg,
    marginTop: -20,
    borderRadius: radius.xl,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: c.border,
    // Soft shadow
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
  showHide:   { fontSize: fontSize.sm, fontWeight: fontWeight.medium },
  input: {
    backgroundColor: c.surfaceMuted,
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 4,
    fontSize: fontSize.base,
  },

  errorBox:   { borderRadius: radius.md, borderWidth: 1, padding: spacing.sm + 2, marginBottom: spacing.sm },
  errorText:  { fontSize: fontSize.sm, fontWeight: fontWeight.medium },

  btn: {
    marginTop: spacing.xs,
    borderRadius: radius.md,
    paddingVertical: spacing.sm + 6,
    alignItems: 'center',
  },
  btnText:    { color: '#fff', fontSize: fontSize.base, fontWeight: fontWeight.semibold, letterSpacing: 0.2 },

  hint: {
    textAlign: 'center',
    fontSize: fontSize.xs,
    lineHeight: 18,
    marginTop: spacing.xl,
    marginBottom: spacing.xl,
    paddingHorizontal: spacing.lg,
  },
});
