/**
 * Your own sign-in name on mobile (ADR-566 D4) -- the twin of web's
 * SignInNameSection. One component for the tenant and platform account
 * screens so the rules and wording can't drift.
 *
 * Only the person chooses it; an admin can only clear one. Cognito enforces
 * uniqueness; the client checks the shape and shows the server's answer.
 * The host renders this only when the pool supports sign-in names.
 */
import React, { useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { Button, tick } from '@components/ui/primitives';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// Mirrors sign_in_name.normalise on the server.
const SHAPE = /^[a-z][a-z0-9._-]{2,29}$/;
export const SIGN_IN_NAME_RULES =
  '3–30 characters: letters, numbers, dots, dashes or underscores, starting with a letter.';

type Props = { path: string; current: string | null; username: string };

export default function SignInNameCard({ path, current, username }: Props) {
  const c = useColors();
  const s = styles(c);
  const [name, setName] = useState<string | null>(current);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cleaned = draft.trim().toLowerCase();

  const save = async () => {
    if (!SHAPE.test(cleaned)) { setError(SIGN_IN_NAME_RULES); return; }
    if (cleaned === username.toLowerCase()) { setError("That's already your username. Choose something different."); return; }
    setBusy(true); setError(null);
    try {
      const { data } = await apiClient.put<{ sign_in_name: string }>(path, { sign_in_name: cleaned });
      setName(data.sign_in_name); setEditing(false); tick();
    } catch (err) {
      setError(errorText(err, "Couldn't save your sign-in name."));
    } finally { setBusy(false); }
  };

  const remove = async () => {
    setBusy(true); setError(null);
    try {
      await apiClient.delete(path);
      setName(null); setEditing(false); tick();
    } catch (err) {
      setError(errorText(err, "Couldn't remove your sign-in name."));
    } finally { setBusy(false); }
  };

  if (!editing) {
    return (
      <View style={s.wrap}>
        <Text style={s.label}>Sign-in name</Text>
        <Text style={name ? s.value : s.muted} selectable={!!name}>{name ?? 'None yet'}</Text>
        <Text style={s.muted}>
          A second name you can sign in with. Your username, {username}, keeps working.
        </Text>
        <Button variant="secondary" onPress={() => { setDraft(name ?? ''); setEditing(true); setError(null); }} fullWidth>
          {name ? 'Change sign-in name' : 'Add a sign-in name'}
        </Button>
      </View>
    );
  }

  return (
    <View style={s.wrap}>
      <Text style={s.label}>Sign-in name</Text>
      <TextInput style={s.input} value={draft} onChangeText={t => { setDraft(t); setError(null); }}
                 autoCapitalize="none" autoCorrect={false} spellCheck={false} maxLength={30}
                 textContentType="username" autoComplete="off" returnKeyType="done"
                 onSubmitEditing={() => void save()}
                 placeholder="sign-in name" placeholderTextColor={c.placeholder}
                 accessibilityLabel="Sign-in name" accessibilityHint={SIGN_IN_NAME_RULES} />
      <Text style={s.muted}>{SIGN_IN_NAME_RULES}</Text>
      {error && <Text style={s.error} accessibilityRole="alert">{error}</Text>}
      <Button onPress={() => void save()} loading={busy} disabled={!cleaned || cleaned === name} fullWidth>Save</Button>
      {name && <Button variant="ghost" onPress={() => void remove()} disabled={busy}>Remove sign-in name</Button>}
      <Button variant="ghost" onPress={() => { setEditing(false); setError(null); }}>Cancel</Button>
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  wrap:  { gap: spacing.sm },
  label: { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.foreground },
  value: { fontSize: fontSize.base, color: c.foreground, fontWeight: fontWeight.medium },
  muted: { fontSize: fontSize.sm, color: c.mutedForeground, lineHeight: 20 },
  error: { fontSize: fontSize.sm, color: c.danger },
  input: { borderWidth: 1, borderColor: c.border, borderRadius: radius.md, paddingHorizontal: spacing.md,
           paddingVertical: spacing.sm + 2, fontSize: fontSize.base, color: c.foreground, backgroundColor: c.background },
});
