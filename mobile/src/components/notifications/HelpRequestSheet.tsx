/**
 * What "Driver Needs Help" opens on the phone (ADR-519 D5): that one request.
 * A sheet, not a tab: there is no list of help requests to navigate to.
 */
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Linking, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { useColors } from '@contexts/ThemeContext';
import { useNotifications } from '@contexts/NotificationsContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { Button, MIN_TARGET } from '@components/ui/primitives';
import { useReducedMotionState } from '../../hooks/useReducedMotionState';

type HelpRequest = {
  id: string; date: string; check_in_number: number; routes_remaining: number;
  working_crew_count: number; ncns_count: number; submitted_at: string | null;
  driver: { id: string; name: string | null; phone: string | null };
  truck: { id: string; name: string } | null;
};

export default function HelpRequestSheet() {
  const c = useColors(); const s = styles(c);
  const insets = useSafeAreaInsets();
  const reduced = useReducedMotionState();
  const { helpRequestId, openHelpRequest } = useNotifications();
  const [req, setReq] = useState<HelpRequest | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    setReq(null); setError('');
    if (!helpRequestId) return;
    apiClient.get(`/shift-ops/help-requests/${helpRequestId}`)
      .then(r => setReq(r.data))
      .catch(e => setError(errorText(e, 'This help request is no longer available.')));
  }, [helpRequestId]);

  const close = () => openHelpRequest(null);
  const day = req ? new Date(`${req.date}T12:00:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }) : '';

  return (
    <Modal visible={!!helpRequestId} transparent animationType={reduced ? 'none' : 'slide'} onRequestClose={close}>
      <Pressable style={s.scrim} onPress={close} accessibilityLabel="Close" />
      <View style={[s.sheet, { paddingBottom: insets.bottom + spacing.md }]}>
        <View style={s.grabber} />
        <Text style={s.title} accessibilityRole="header">🆘 Help requested</Text>
        {!req && !error && <ActivityIndicator color={c.primary} />}
        {!!error && <Text style={s.muted}>{error}</Text>}
        {req && (
          <>
            <Text style={s.name}>{req.driver.name ?? 'Driver'}</Text>
            <Text style={s.muted}>{req.truck ? `${req.truck.name} · ` : ''}{day}</Text>
            <View style={s.grid}>
              {([['Check-in', `#${req.check_in_number}`], ['Routes left', String(req.routes_remaining)],
                 ['Crew working', String(req.working_crew_count)], ['No-shows', String(req.ncns_count)]] as const)
                .map(([k, v]) => (
                  <View key={k} style={s.cell}>
                    <Text style={s.cellK}>{k}</Text>
                    <Text style={s.cellV}>{v}</Text>
                  </View>
                ))}
            </View>
            {req.driver.phone ? (
              <>
                <Text style={s.phone} selectable>{req.driver.phone}</Text>
                <Button fullWidth onPress={() => { Linking.openURL(`tel:${req.driver.phone}`).catch(() => {}); }}>
                  Call driver
                </Button>
              </>
            ) : <Text style={s.muted}>Phone not shown</Text>}
          </>
        )}
        <View style={s.closeRow}><Button variant="secondary" fullWidth onPress={close}>Close</Button></View>
      </View>
    </Modal>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  scrim: { flex: 1, backgroundColor: 'rgba(0,0,0,0.55)' },   // the scrim InterruptiveSheet uses
  sheet: { backgroundColor: c.card, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.md, gap: spacing.sm },
  grabber: { alignSelf: 'center', width: 40, height: 4, borderRadius: 2, backgroundColor: c.border },
  title: { fontSize: fontSize.lg, fontWeight: fontWeight.bold, color: c.danger },
  name: { fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.foreground },
  muted: { fontSize: fontSize.sm, color: c.mutedForeground },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.xs },
  cell: { flexBasis: '48%', flexGrow: 1, borderWidth: 1, borderColor: c.border, borderRadius: radius.md, padding: spacing.sm },
  cellK: { fontSize: fontSize.xs, color: c.mutedForeground },
  cellV: { fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.foreground, fontVariant: ['tabular-nums'] },
  phone: { fontSize: fontSize.base, color: c.foreground, fontVariant: ['tabular-nums'], minHeight: MIN_TARGET, textAlignVertical: 'center' },
  closeRow: { marginTop: spacing.xs },
});
