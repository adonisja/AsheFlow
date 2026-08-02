/**
 * Found a package that isn't on your route (ADR-246).
 *
 * A walker opens a tote and finds a package that was never registered. Until
 * now there was no way to record it, so the delivery either went untracked or
 * the package came back.
 *
 * Two steps, deliberately: PREVIEW then CONFIRM. The preview writes nothing and
 * answers the questions the walker cannot answer themselves — is this even ours,
 * is someone already carrying it, is another route a better fit. Committing
 * straight from the form would hide all three behind a spinner.
 *
 * The screen has to work one-handed in a van, so the confirm step is a single
 * large button and every outcome resolves to one sentence.
 */
import React, { useCallback, useState } from 'react';
import {
  ActivityIndicator, KeyboardAvoidingView, Platform, ScrollView, StyleSheet,
  Text, TextInput, TouchableOpacity, View,
} from 'react-native';
import ScreenShell from '@components/ui/ScreenShell';
import apiClient from '@api/client';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';
import { Badge } from '@components/ui/primitives';

// ── Types ─────────────────────────────────────────────────────────────────────

type Candidate = {
  route_id: string;
  route_number: number | null;
  walker_name: string | null;
  status: string | null;
  can_accept: boolean;
  match: string;
  is_adders_route: boolean;
};

type Assessment = {
  in_zone: boolean;
  decidable: boolean;
  zone_reason: string | null;
  best_fit: Candidate | null;
  adders_route: Candidate | null;
  candidates: Candidate[];
  absorbed_reason: string | null;
};

type IntakeResult = {
  outcome: 'added' | 'duplicate' | 'removal' | 'needs_dispatch';
  tba: string;
  route_id: string | null;
  route_number: number | null;
  walker_name: string | null;
  stop_id: string | null;
  removal_id: string | null;
  reason: string | null;
  existing_holder: string | null;
  existing_route_number: number | null;
  assessment: Assessment | null;
};

// ── Outcome copy ──────────────────────────────────────────────────────────────

/**
 * One sentence per outcome, written for someone holding a package.
 *
 * The duplicate case NAMES the holder rather than just refusing — a bare
 * "already registered" sends the walker off to find out who has it, and two
 * people holding the same TBA is itself worth surfacing (ADR-246).
 */
function outcomeCopy(r: IntakeResult): { title: string; body: string; tone: string } {
  switch (r.outcome) {
    case 'added':
      return {
        tone: 'success',
        title: r.route_number ? `Added to Route ${r.route_number}` : 'Added to your route',
        body: r.reason?.startsWith('best_fit_in_progress')
          ? 'The closest route has already departed, so this was absorbed into a route that can still take it.'
          : 'Deliver it as normal. It will not count against the Amazon reconciliation.',
      };
    case 'duplicate':
      return {
        tone: 'warning',
        title: 'Already registered',
        body: r.existing_holder
          ? `${r.existing_holder}${r.existing_route_number ? ` (Route ${r.existing_route_number})` : ''} already has this package. If you are both holding one, the label may be wrong — tell dispatch.`
          : 'This package is already on a route. Nothing was changed.',
      };
    case 'removal':
      return {
        tone: 'danger',
        title: 'Not ours to deliver',
        body: 'This address is outside the company zone. Hand it to your driver — it is logged for return to the station.',
      };
    default:
      return {
        tone: 'info',
        title: 'Sent to dispatch',
        body: r.reason === 'no_coords' || r.reason === 'no_boundary'
          ? 'We could not place the address, so dispatch will resolve it. Keep the package for now.'
          : 'No route can take this right now. Dispatch will decide where it goes.',
      };
  }
}

// ── Screen ────────────────────────────────────────────────────────────────────

export default function FoundPackageScreen() {
  const c = useColors();
  const s = styles(c);

  const [tba, setTba] = useState('');
  const [address, setAddress] = useState('');
  const [preview, setPreview] = useState<IntakeResult | null>(null);
  const [result, setResult] = useState<IntakeResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const body = useCallback((override: boolean) => ({
    tba: tba.trim().toUpperCase(),
    normalised_address: address.trim() || null,
    accept_override: override,
  }), [tba, address]);

  const runPreview = useCallback(async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await apiClient.post<IntakeResult>('/packages/intake/preview', body(false));
      setPreview(res.data);
    } catch {
      setError('Could not check this package. Try again.');
    } finally {
      setBusy(false);
    }
  }, [body]);

  const confirm = useCallback(async (override: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const res = await apiClient.post<IntakeResult>('/packages/intake', body(override));
      setResult(res.data);
      setPreview(null);
    } catch {
      setError('Could not save this package. Try again.');
    } finally {
      setBusy(false);
    }
  }, [body]);

  const reset = useCallback(() => {
    setTba('');
    setAddress('');
    setPreview(null);
    setResult(null);
    setError(null);
  }, []);

  // A better-fit route exists that is not the walker's own. Advisory, not a
  // gate: the package is already in their tote (ADR-246).
  const betterFit =
    preview?.assessment?.best_fit &&
    !preview.assessment.best_fit.is_adders_route &&
    preview.assessment.best_fit.can_accept
      ? preview.assessment.best_fit
      : null;

  const canSubmit = tba.trim().length >= 4 && !busy;

  return (
    <ScreenShell title="Found a package">
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={s.flex}
      >
        <ScrollView contentContainerStyle={s.content} keyboardShouldPersistTaps="handled">
          {result ? (
            <ResultCard result={result} onDone={reset} c={c} />
          ) : (
            <>
              <Text style={s.hint}>
                A package in your tote that isn&apos;t on your route. We&apos;ll check
                whether it&apos;s ours and where it belongs before anything is saved.
              </Text>

              <Text style={s.label}>Tracking number (TBA)</Text>
              <TextInput
                style={s.input}
                value={tba}
                onChangeText={(t) => { setTba(t); setPreview(null); }}
                placeholder="TBA303912345447"
                placeholderTextColor={c.mutedForeground}
                autoCapitalize="characters"
                autoCorrect={false}
                editable={!busy}
              />

              <Text style={s.label}>Address on the label</Text>
              <TextInput
                style={s.input}
                value={address}
                onChangeText={(t) => { setAddress(t); setPreview(null); }}
                placeholder="1 Main St"
                placeholderTextColor={c.mutedForeground}
                autoCorrect={false}
                editable={!busy}
              />

              {error && <Text style={s.error}>{error}</Text>}

              {preview && (
                <PreviewCard preview={preview} betterFit={betterFit} c={c} />
              )}

              {busy && <ActivityIndicator color={c.primary} style={s.spinner} />}

              {!preview ? (
                <TouchableOpacity
                  style={[s.primaryBtn, !canSubmit && s.btnDisabled]}
                  onPress={runPreview}
                  disabled={!canSubmit}
                >
                  <Text style={s.primaryBtnText}>Check package</Text>
                </TouchableOpacity>
              ) : preview.outcome === 'duplicate' || preview.outcome === 'removal' ? (
                // Nothing to confirm — the preview already tells the whole story.
                <TouchableOpacity style={s.secondaryBtn} onPress={reset}>
                  <Text style={s.secondaryBtnText}>Start over</Text>
                </TouchableOpacity>
              ) : (
                <>
                  <TouchableOpacity
                    style={[s.primaryBtn, busy && s.btnDisabled]}
                    onPress={() => confirm(false)}
                    disabled={busy}
                  >
                    <Text style={s.primaryBtnText}>
                      {betterFit ? 'Take it anyway' : 'Add to my route'}
                    </Text>
                  </TouchableOpacity>
                  {betterFit && (
                    <TouchableOpacity
                      style={s.secondaryBtn}
                      onPress={() => confirm(true)}
                      disabled={busy}
                    >
                      <Text style={s.secondaryBtnText}>
                        Send to Route {betterFit.route_number}
                      </Text>
                    </TouchableOpacity>
                  )}
                </>
              )}
            </>
          )}
        </ScrollView>
      </KeyboardAvoidingView>
    </ScreenShell>
  );
}

function PreviewCard({
  preview, betterFit, c,
}: { preview: IntakeResult; betterFit: Candidate | null; c: ThemeColors }) {
  const s = styles(c);
  const copy = outcomeCopy(preview);
  const tone =
    copy.tone === 'success' ? c.success
      : copy.tone === 'warning' ? c.warning
        : copy.tone === 'danger' ? c.danger : c.info;

  return (
    <View style={[s.card, { borderColor: tone }]}>
      <Text style={[s.cardTitle, { color: tone }]}>{copy.title}</Text>
      <Text style={s.cardBody}>{copy.body}</Text>
      {betterFit && (
        <Text style={s.cardNote}>
          Route {betterFit.route_number}
          {betterFit.walker_name ? ` (${betterFit.walker_name})` : ''} is a closer
          match. You can still take it — it&apos;s already in your tote.
        </Text>
      )}
    </View>
  );
}

function ResultCard({
  result, onDone, c,
}: { result: IntakeResult; onDone: () => void; c: ThemeColors }) {
  const s = styles(c);
  const copy = outcomeCopy(result);
  const tone =
    copy.tone === 'success' ? c.success
      : copy.tone === 'warning' ? c.warning
        : copy.tone === 'danger' ? c.danger : c.info;

  return (
    <View style={s.resultWrap}>
      <Badge tone="muted">{result.tba}</Badge>
      <Text style={[s.resultTitle, { color: tone }]}>{copy.title}</Text>
      <Text style={s.cardBody}>{copy.body}</Text>
      <TouchableOpacity style={s.primaryBtn} onPress={onDone}>
        <Text style={s.primaryBtnText}>Add another</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  flex: { flex: 1 },
  content: { padding: spacing.lg, gap: spacing.sm },
  hint: {
    color: c.mutedForeground, fontSize: fontSize.sm, marginBottom: spacing.sm,
    lineHeight: 20,
  },
  label: {
    color: c.foreground, fontSize: fontSize.sm, fontWeight: fontWeight.medium,
    marginTop: spacing.sm,
  },
  input: {
    backgroundColor: c.card, borderColor: c.border, borderWidth: 1,
    borderRadius: radius.md, padding: spacing.md, color: c.foreground,
    fontSize: fontSize.base,
  },
  error: { color: c.danger, fontSize: fontSize.sm, marginTop: spacing.sm },
  spinner: { marginTop: spacing.md },
  card: {
    borderWidth: 1, borderRadius: radius.lg, padding: spacing.md,
    marginTop: spacing.md, backgroundColor: c.card, gap: spacing.xs,
  },
  cardTitle: { fontSize: fontSize.base, fontWeight: fontWeight.semibold },
  cardBody: { color: c.foreground, fontSize: fontSize.sm, lineHeight: 20 },
  cardNote: {
    color: c.mutedForeground, fontSize: fontSize.sm, lineHeight: 20,
    marginTop: spacing.xs,
  },
  resultWrap: { gap: spacing.md, alignItems: 'flex-start' },
  resultTitle: { fontSize: fontSize.lg, fontWeight: fontWeight.bold },
  primaryBtn: {
    backgroundColor: c.primary, borderRadius: radius.md, padding: spacing.md,
    alignItems: 'center', marginTop: spacing.md, alignSelf: 'stretch',
  },
  primaryBtnText: {
    color: c.primaryForeground, fontSize: fontSize.base,
    fontWeight: fontWeight.semibold,
  },
  secondaryBtn: {
    borderColor: c.border, borderWidth: 1, borderRadius: radius.md,
    padding: spacing.md, alignItems: 'center', marginTop: spacing.sm,
    alignSelf: 'stretch',
  },
  secondaryBtnText: { color: c.foreground, fontSize: fontSize.base },
  btnDisabled: { opacity: 0.5 },
});
