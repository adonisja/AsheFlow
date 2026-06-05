import React, { useCallback, useState } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ActivityIndicator,
} from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

type Credentials = {
  flex_email: string;
  clock_in_code: string;
  sent_at: string;
  updated_at: string;
};

export default function MyCredentialsScreen() {
  const c = useColors();
  const [creds, setCreds]             = useState<Credentials | null>(null);
  const [loading, setLoading]         = useState(true);
  const [showEmail, setShowEmail]     = useState(false);
  const [showCode, setShowCode]       = useState(false);
  const [refreshing, setRefreshing]   = useState(false);

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

  const s = styles(c);

  if (!loading && !creds) {
    return (
      <ScreenShell title="My Credentials">
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
      title="My Credentials"
      loading={loading}
      refreshing={refreshing}
      onRefresh={() => { setRefreshing(true); load(); }}
    >
      {creds && (
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
            Last updated {new Date(creds.updated_at).toLocaleDateString()}
          </Text>
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

  empty:       { alignItems: 'center', marginTop: spacing.xxl, gap: spacing.sm },
  emptyIcon:   { fontSize: 48 },
  emptyTitle:  { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.foreground },
  emptySub:    { fontSize: fontSize.sm, color: c.mutedForeground, textAlign: 'center' },
});
