/**
 * My Credentials — the temporary Flex login management issued (ADR-124).
 *
 * ADR-491: AsheFlow holds these only for the handoff. The trainee signs in,
 * changes both, and taps "I've changed both", which destroys the stored copy.
 * Unconfirmed, they are destroyed 14 days after sending. Once gone, this screen
 * says how they ended instead of showing an empty state.
 */
import React, { useCallback, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, Alert, ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { tick } from '@components/ui/primitives';

// Mirrors the server's MyCredentials (ADR-491 D4). The values are null once the
// handoff has ended — confirmed or expired.
type Credentials = {
  flex_email: string | null;
  clock_in_code: string | null;
  sent_at: string;
  updated_at: string;
  confirmed_at?: string | null;
  expired_at?: string | null;
  expires_at?: string | null;
};

export default function MyCredentialsScreen() {
  const c = useColors();
  const [creds, setCreds]             = useState<Credentials | null>(null);
  const [loading, setLoading]         = useState(true);
  const [showEmail, setShowEmail]     = useState(false);
  const [showCode, setShowCode]       = useState(false);
  const [refreshing, setRefreshing]   = useState(false);
  const [confirming, setConfirming]   = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get('/trainee-credentials/mine');
      setCreds(res.data);
    } catch (e: any) {
      if (e?.response?.status === 404) {
        setCreds(null);
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const confirmChanged = () => {
    Alert.alert(
      'Changed both?',
      'Only confirm once you have signed in to Flex and changed your email password and clock-in code. AsheFlow will then delete its copy — your manager would have to re-send them.',
      [
        { text: 'Not yet', style: 'cancel' },
        {
          text: "Yes, I've changed both",
          onPress: async () => {
            setConfirming(true);
            try {
              const res = await apiClient.post('/trainee-credentials/mine/confirm');
              tick();
              setCreds(res.data);
            } catch (e: any) {
              Alert.alert('Could not confirm', e?.response?.data?.detail ?? 'Try again in a moment.');
            } finally {
              setConfirming(false);
            }
          },
        },
      ],
    );
  };

  const s = styles(c);

  if (!loading && !creds) {
    return (
      <ScreenShell noHeader>
        <View style={s.empty}>
          <Text style={s.emptyIcon}>🔑</Text>
          <Text style={s.emptyTitle}>No credentials yet</Text>
          <Text style={s.emptySub}>Your manager will send these on your first day.</Text>
        </View>
      </ScreenShell>
    );
  }

  return (
    <ScreenShell
      noHeader
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => { setRefreshing(true); load(); }}
    >
      {creds && !creds.flex_email && (
        <View style={s.empty}>
          <Text style={s.emptyIcon}>{creds.confirmed_at ? '✅' : '⌛'}</Text>
          <Text style={s.emptyTitle}>
            {creds.confirmed_at ? 'You changed your credentials' : 'These credentials expired'}
          </Text>
          <Text style={s.emptySub}>
            {creds.confirmed_at
              ? `Confirmed ${new Date(creds.confirmed_at).toLocaleDateString()}. AsheFlow no longer stores them.`
              : 'They were removed after 14 days. Ask your manager to re-send them if you have not signed in yet.'}
          </Text>
        </View>
      )}

      {creds && creds.flex_email && (
        <>
          <View style={s.card}>
            <Text style={s.cardHeader}>Flex Account Email</Text>
            <View style={s.revealRow}>
              <Text style={[s.value, !showEmail && s.masked]}>
                {showEmail ? creds.flex_email : '••••••••••••••••'}
              </Text>
              <TouchableOpacity onPress={() => setShowEmail(v => !v)} style={s.toggleBtn}>
                <Text style={[s.toggleText, { color: c.primary }]}>
                  {showEmail ? 'Hide' : 'Reveal'}
                </Text>
              </TouchableOpacity>
            </View>
          </View>

          <View style={s.card}>
            <Text style={s.cardHeader}>Clock-In Code</Text>
            <View style={s.revealRow}>
              <Text style={[s.value, !showCode && s.masked]}>
                {showCode ? creds.clock_in_code : '••••••••'}
              </Text>
              <TouchableOpacity onPress={() => setShowCode(v => !v)} style={s.toggleBtn}>
                <Text style={[s.toggleText, { color: c.primary }]}>
                  {showCode ? 'Hide' : 'Reveal'}
                </Text>
              </TouchableOpacity>
            </View>
          </View>

          <Text style={s.hint}>
            Sent {new Date(creds.sent_at).toLocaleDateString()}
            {creds.expires_at ? ` · removed ${new Date(creds.expires_at).toLocaleDateString()} if not confirmed` : ''}
          </Text>

          <Text style={s.instructions}>
            These are temporary. Sign in to Flex, change both, then confirm below.
          </Text>
          <TouchableOpacity
            style={[s.confirmBtn, { backgroundColor: c.primary }, confirming && { opacity: 0.6 }]}
            onPress={confirmChanged}
            disabled={confirming}
            accessibilityRole="button"
            accessibilityLabel="I've signed in and changed both"
          >
            {confirming
              ? <ActivityIndicator color={c.primaryForeground} />
              : <Text style={[s.confirmText, { color: c.primaryForeground }]}>I've signed in and changed both</Text>}
          </TouchableOpacity>
        </>
      )}
    </ScreenShell>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  card:        { backgroundColor: c.card, borderRadius: radius.lg, borderWidth: 1, borderColor: c.border, padding: spacing.md, marginBottom: spacing.md },
  cardHeader:  { fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.mutedForeground, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: spacing.sm },
  revealRow:   { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: spacing.sm },
  value:       { fontSize: fontSize.md, color: c.foreground, fontWeight: fontWeight.medium, flex: 1 },
  masked:      { letterSpacing: 4 },
  toggleBtn:   { paddingVertical: spacing.xs, paddingHorizontal: spacing.sm },
  toggleText:  { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  hint:        { fontSize: fontSize.xs, color: c.mutedForeground, textAlign: 'center', marginTop: spacing.xs },
  instructions:{ fontSize: fontSize.sm, color: c.foreground, textAlign: 'center', marginTop: spacing.lg, marginBottom: spacing.sm },
  confirmBtn:  { borderRadius: radius.lg, paddingVertical: spacing.md, alignItems: 'center', minHeight: 48, justifyContent: 'center' },
  confirmText: { fontSize: fontSize.md, fontWeight: fontWeight.semibold },

  empty:       { alignItems: 'center', marginTop: spacing.xxl, gap: spacing.sm },
  emptyIcon:   { fontSize: 48 },
  emptyTitle:  { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.foreground },
  emptySub:    { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center' },
});
