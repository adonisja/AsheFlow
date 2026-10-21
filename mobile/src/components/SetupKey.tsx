/**
 * The authenticator setup key, made so nobody has to retype it (ADR-557).
 *
 * A phone can't scan its own screen, so on mobile this key IS the enrolment
 * path, and a 32-character base32 string copied by hand fails silently: the
 * codes just never match (owner, 2026-10-21: "writing it down causes a lot of
 * errors").
 *
 *  1. "Add to authenticator app" opens the standard otpauth:// URI, which
 *     Google/Microsoft Authenticator, 1Password, Authy and iOS Passwords all
 *     register, so the account is added with nothing typed.
 *  2. "Copy key" copies the raw key; the screen shows it in groups of four.
 *     The clipboard is cleared after two minutes if it still holds the key.
 */
import React, { useEffect, useRef, useState } from 'react';
import { Linking, Platform, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import Clipboard from '@react-native-clipboard/clipboard';
import { useColors } from '@contexts/ThemeContext';
import { groupKey, otpauthUri, rawKey } from './setupKeyFormat';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

const CLEAR_AFTER_MS = 2 * 60 * 1000;

type Props = { secret: string; account: string };

export default function SetupKey({ secret, account }: Props) {
  const c = useColors();
  const s = styles(c);
  const [copied, setCopied] = useState(false);
  const [noApp, setNoApp] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const openInApp = async () => {
    setNoApp(false);
    try {
      // openURL, not canOpenURL: the latter needs the scheme declared per
      // platform and answers "no" without it. openURL rejects when nothing
      // handles otpauth://, which is the signal we want.
      await Linking.openURL(otpauthUri(secret, account));
    } catch {
      setNoApp(true);
    }
  };

  const copy = () => {
    const raw = rawKey(secret);
    Clipboard.setString(raw);
    setCopied(true);
    timers.current.push(setTimeout(() => setCopied(false), 2000));
    // Like a password manager: don't leave a long-lived secret on the
    // clipboard, where other apps can read it. Only clear it if it's still ours.
    timers.current.push(setTimeout(async () => {
      try { if ((await Clipboard.getString()) === raw) Clipboard.setString(''); } catch { /* ignore */ }
    }, CLEAR_AFTER_MS));
  };

  return (
    <View style={s.wrap}>
      <TouchableOpacity style={s.primary} onPress={() => void openInApp()} accessibilityRole="button">
        <Text style={s.primaryText}>Add to authenticator app</Text>
      </TouchableOpacity>
      {noApp && (
        <Text style={s.warn} accessibilityLiveRegion="polite">
          No authenticator app on this {Platform.OS === 'ios' ? 'iPhone' : 'phone'} opened it. Install one, or copy
          the key below and add it by hand.
        </Text>
      )}

      <Text style={s.or}>or add it by hand</Text>
      <View style={s.keyRow}>
        <Text selectable style={s.key} accessibilityLabel={`Setup key ${secret.split('').join(' ')}`}>
          {groupKey(secret)}
        </Text>
        <TouchableOpacity onPress={copy} style={s.copy} accessibilityRole="button"
                          accessibilityLabel={copied ? 'Key copied' : 'Copy key'}>
          <Text style={s.copyText}>{copied ? 'Copied' : 'Copy key'}</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const mono = Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' });

const styles = (c: ThemeColors) => StyleSheet.create({
  wrap:        { gap: spacing.sm },
  primary:     { backgroundColor: c.primary, padding: spacing.md, borderRadius: radius.md, alignItems: 'center' },
  primaryText: { color: c.primaryForeground, fontWeight: fontWeight.semibold, fontSize: fontSize.md },
  warn:        { fontSize: fontSize.sm, color: c.warning, lineHeight: 20 },
  or:          { fontSize: fontSize.xs, color: c.mutedForeground, textAlign: 'center', marginTop: spacing.xs },
  keyRow:      { flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
                 backgroundColor: c.accent, borderRadius: radius.md, paddingLeft: spacing.md,
                 paddingVertical: spacing.xs, paddingRight: spacing.xs },
  key:         { flex: 1, fontFamily: mono, fontSize: fontSize.sm + 1, color: c.foreground, lineHeight: 22 },
  // Compact (owner, 2026-10-21: "too big"): a small pill, not a second button.
  copy:        { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999,
                 borderWidth: 1, borderColor: c.border, backgroundColor: c.background },
  copyText:    { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.primary },
});
