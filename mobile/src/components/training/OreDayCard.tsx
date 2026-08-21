/**
 * ADR-281 — the ORE day (phase 0), on mobile.
 *
 * ORE itself happens on Amazon AtoZ; this card covers the two things AsheFlow
 * owns on that day: proof the course was completed, and whether the trainee
 * stayed afterwards.
 *
 * Renders only for phase 0. Every other phase gets its existing task list.
 */
import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Linking,
} from 'react-native';
import apiClient from '@api/client';
import { errorText } from '@api/errorText';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

const ORE_LINK =
  'https://atoz.amazon.work/learn/rustici/launch' +
  '?trainingPath=%5B%22TCRLERN20240917180409e3c8b8ca%22%5D';

export type OreState = {
  recordId: string;
  oreCompletedAt: string | null;
  hasCertificate: boolean;
  leftEarly: boolean;
};

export default function OreDayCard({
  state,
  c,
  canMarkLeftEarly,
  onChanged,
}: {
  state: OreState;
  c: ThemeColors;
  /** Trainers and dispatch record the departure; a trainee does not mark
   *  their own pay-affecting attendance. */
  canMarkLeftEarly: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const upload = async () => {
    setBusy(true);
    try {
      const { launchImageLibrary, launchCamera } = await import('react-native-image-picker');

      // A certificate is usually a PDF or a screenshot already on the phone,
      // so the library is the first stop — but AtoZ shows it on screen, so
      // photographing it has to work too.
      const pick = await new Promise<Awaited<ReturnType<typeof launchCamera>>>((resolve) => {
        Alert.alert(
          'ORE certificate',
          'Where is your completion certificate?',
          [
            {
              text: 'Photos / Files',
              onPress: () =>
                resolve(launchImageLibrary({ mediaType: 'photo', quality: 0.9 })),
            },
            {
              text: 'Take a photo',
              onPress: () =>
                resolve(
                  launchCamera({
                    mediaType: 'photo',
                    // Full-resolution photos run several MB and the endpoint
                    // caps at 10; the text only needs to be legible.
                    maxWidth: 2000,
                    maxHeight: 2000,
                    quality: 0.8,
                    saveToPhotos: false,
                  }),
                ),
            },
            { text: 'Cancel', style: 'cancel', onPress: () => resolve({ didCancel: true } as never) },
          ],
          { cancelable: true },
        );
      });

      if (pick.didCancel) { setBusy(false); return; }
      const asset = pick.assets?.[0];
      if (pick.errorCode || !asset?.uri) {
        Alert.alert(
          'Could not open',
          pick.errorCode === 'permission'
            ? 'Photo access is off. Turn it on in Settings, or ask your trainer to upload it for you.'
            : 'Could not open the picker. Ask your trainer to upload it for you.',
        );
        setBusy(false);
        return;
      }

      const form = new FormData();
      form.append('file', {
        uri: asset.uri,
        type: asset.type ?? 'image/jpeg',
        name: asset.fileName ?? 'ore-certificate.jpg',
      } as unknown as Blob);

      await apiClient.post(
        `/training/record/${state.recordId}/ore-certificate`,
        form,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      );
      Alert.alert('Uploaded', 'Your ORE certificate has been recorded.');
      onChanged();
    } catch (e) {
      Alert.alert('Upload failed', errorText(e, 'Could not upload the certificate.'));
    } finally {
      setBusy(false);
    }
  };

  const markLeftEarly = () => {
    Alert.alert(
      'Leaving for the day?',
      'This records that ORE is done and you left. It affects pay for today and ' +
        'dispatch is notified. It is not a mark against you.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Record departure',
          style: 'destructive',
          onPress: async () => {
            setBusy(true);
            try {
              await apiClient.post(`/training/record/${state.recordId}/left-early`);
              onChanged();
            } catch (e) {
              Alert.alert('Failed', errorText(e, 'Could not record the departure.'));
            } finally {
              setBusy(false);
            }
          },
        },
      ],
    );
  };

  const done = !!state.oreCompletedAt;

  return (
    <View style={[s.card, { backgroundColor: c.card, borderColor: c.border }]}>
      <Text style={[s.title, { color: c.foreground }]}>ORE training</Text>
      <Text style={[s.sub, { color: c.mutedForeground }]}>
        Your first day. The course runs on Amazon AtoZ — upload the certificate
        here when you finish.
      </Text>

      <TouchableOpacity
        onPress={() => Linking.openURL(ORE_LINK)}
        style={[s.link, { borderColor: c.border }]}
      >
        <Text style={[s.linkText, { color: c.primary }]}>Open ORE on AtoZ →</Text>
      </TouchableOpacity>

      <View style={[s.status, { borderTopColor: c.border }]}>
        {done ? (
          <>
            <Text style={[s.statusText, { color: c.success }]}>
              ✓ Certificate recorded
            </Text>
            {/* The attestation outlives the file (ADR-281 D2), so say so
                rather than implying the record is gone. */}
            {!state.hasCertificate && (
              <Text style={[s.note, { color: c.mutedForeground }]}>
                The uploaded file has passed its 48-hour retention window. Your
                completion is still on record.
              </Text>
            )}
          </>
        ) : (
          <Text style={[s.statusText, { color: c.mutedForeground }]}>
            No certificate uploaded yet
          </Text>
        )}
      </View>

      {busy ? (
        <ActivityIndicator color={c.primary} style={{ marginTop: spacing.sm }} />
      ) : (
        <View style={s.actions}>
          <TouchableOpacity
            onPress={upload}
            style={[s.btn, { backgroundColor: c.primary }]}
          >
            <Text style={[s.btnText, { color: c.primaryForeground }]}>
              {done ? 'Replace certificate' : 'Upload certificate'}
            </Text>
          </TouchableOpacity>

          {/* Only offered once ORE is done — "leaving early" is a choice that
              exists AFTER the course, not instead of it. */}
          {canMarkLeftEarly && done && !state.leftEarly && (
            <TouchableOpacity
              onPress={markLeftEarly}
              style={[s.btnGhost, { borderColor: c.border }]}
            >
              <Text style={[s.btnGhostText, { color: c.foreground }]}>
                Record leaving for the day
              </Text>
            </TouchableOpacity>
          )}

          {state.leftEarly && (
            <Text style={[s.note, { color: c.mutedForeground }]}>
              Recorded as leaving after ORE. Dispatch has been notified.
            </Text>
          )}
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  title: { fontSize: fontSize.md, fontWeight: fontWeight.bold },
  sub: { fontSize: fontSize.sm, marginTop: 2 },
  link: { borderWidth: 1, borderRadius: radius.sm, paddingVertical: spacing.sm, paddingHorizontal: spacing.md, marginTop: spacing.md, alignItems: 'center' },
  linkText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  status: { borderTopWidth: StyleSheet.hairlineWidth, marginTop: spacing.md, paddingTop: spacing.sm },
  statusText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  note: { fontSize: fontSize.xs, marginTop: 4 },
  actions: { marginTop: spacing.md, gap: spacing.sm },
  btn: { borderRadius: radius.sm, paddingVertical: spacing.sm, alignItems: 'center' },
  btnText: { fontSize: fontSize.sm, fontWeight: fontWeight.semibold },
  btnGhost: { borderWidth: 1, borderRadius: radius.sm, paddingVertical: spacing.sm, alignItems: 'center' },
  btnGhostText: { fontSize: fontSize.sm, fontWeight: fontWeight.medium },
});
