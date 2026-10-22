/**
 * The name you're called in AsheFlow, on mobile (ADR-567) -- the twin of web's
 * ChosenNameSection. Only the person sets it; it is shown everywhere instead
 * of the legal name, which stays the record and is shown here, to them alone.
 */
import React, { useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { Button, tick } from '@components/ui/primitives';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

// A light client check; the server's chosen_name.normalise is the rule. No
// `\p{L}`: Unicode property escapes aren't guaranteed on every Hermes build,
// and a regex that fails to compile would take the whole screen down. So:
// no digits, no characters outside names, and not starting with a symbol.
const SHAPE = /^(?![\s'’.\-=+@])[^0-9=+@<>{}\[\]()*&^%$#!?;:"\\/|_~`]+$/;
export const CHOSEN_NAME_RULES =
  'Up to 100 characters: letters, spaces, apostrophes, hyphens and periods, starting with a letter.';

export type MyNames = { name: string; legal_name?: string; chosen_name?: string | null };
type Props = { legalName: string; chosen: string | null; onChanged: (me: MyNames) => void };

export default function ChosenNameCard({ legalName, chosen, onChanged }: Props) {
  const c = useColors();
  const s = styles(c);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cleaned = draft.trim().replace(/\s+/g, ' ');

  const save = async () => {
    if (!cleaned || cleaned.length > 100 || !SHAPE.test(cleaned)) { setError(CHOSEN_NAME_RULES); return; }
    setBusy(true); setError(null);
    try {
      const { data } = await apiClient.put<MyNames>('/employees/me/chosen-name', { chosen_name: cleaned });
      setEditing(false); tick(); onChanged(data);
    } catch (err) {
      setError(errorText(err, "Couldn't save your name."));
    } finally { setBusy(false); }
  };

  const useLegal = async () => {
    setBusy(true); setError(null);
    try {
      const { data } = await apiClient.delete<MyNames>('/employees/me/chosen-name');
      setEditing(false); tick(); onChanged(data);
    } catch (err) {
      setError(errorText(err, "Couldn't change your name."));
    } finally { setBusy(false); }
  };

  return (
    <View style={s.wrap}>
      <Text style={s.label}>Name shown to others</Text>
      {!editing ? (
        <>
          <Text style={s.value}>{chosen || legalName}</Text>
          {chosen && <Text style={s.muted}>Legal name: {legalName}</Text>}
          <Button variant="secondary" onPress={() => { setDraft(chosen ?? ''); setEditing(true); setError(null); }} fullWidth>
            Change the name others see
          </Button>
        </>
      ) : (
        <>
          <TextInput style={s.input} value={draft} onChangeText={t => { setDraft(t); setError(null); }}
                     maxLength={100} autoCorrect={false} textContentType="nickname" returnKeyType="done"
                     onSubmitEditing={() => void save()} placeholder={legalName} placeholderTextColor={c.placeholder}
                     accessibilityLabel="Name shown to others" accessibilityHint={CHOSEN_NAME_RULES} />
          <Text style={s.muted}>
            Everyone in AsheFlow will see this name instead of your legal name, on every screen and in new messages.
            Your legal name stays on payroll and other official records. Messages sent before the change keep the old name.
          </Text>
          {error && <Text style={s.error} accessibilityRole="alert">{error}</Text>}
          <Button onPress={() => void save()} loading={busy} disabled={!cleaned || cleaned === chosen} fullWidth>Save</Button>
          {chosen && <Button variant="ghost" onPress={() => void useLegal()} disabled={busy}>Use my legal name</Button>}
          <Button variant="ghost" onPress={() => { setEditing(false); setError(null); }}>Cancel</Button>
        </>
      )}
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
