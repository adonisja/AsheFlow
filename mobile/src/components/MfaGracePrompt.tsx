/**
 * The skippable half of the grace period, on mobile (ADR-381 D2).
 *
 * The Profile section shows the countdown, but only to someone who navigates to
 * Settings -- which a walker opening the app to check today's route never does.
 * Without this, the warning half of ADR-377's design was effectively invisible
 * on the device that matters most for field staff, and the first thing they
 * would learn about the deadline is MfaRequiredScreen refusing them.
 *
 * A modal is correct HERE and wrong for the blocked case. While counting down
 * they may still work, so this must be escapable; once blocked they may not, so
 * that one is a navigator swap the tabs cannot be reached around.
 *
 * ONE PROMPT PER LAUNCH. A walker who taps "Not now" has told you something, and
 * re-asking on the next screen change is how a warning becomes noise people
 * dismiss without reading. State lives in the component that mounts once per
 * session, not in storage: a new launch is a new chance to ask, and a deadline
 * that stops mentioning itself is the invisible clock again.
 */
import React, { useState } from 'react';
import { Modal, View, Text, StyleSheet, TouchableOpacity, ScrollView } from 'react-native';

import MfaEnrolment from '@components/MfaEnrolment';
import { useAuth } from '@contexts/AuthContext';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, fontSize, fontWeight, type ThemeColors } from '@theme/index';

export default function MfaGracePrompt() {
  const { mfaStatus, refreshMfaStatus } = useAuth();
  const c = useColors();
  const s = styles(c);
  const [skipped, setSkipped] = useState(false);

  /* `enrolled === null` means Cognito could not be read -- NOT "no MFA
     required". Prompting there nags someone already enrolled because AWS
     hiccuped. `blocked` never reaches this component: RootNavigator swaps the
     whole shell out before MainShell renders. */
  if (!mfaStatus || mfaStatus.enrolled === null) return null;
  if (!mfaStatus.required || mfaStatus.enrolled || mfaStatus.blocked) return null;
  if (skipped) return null;

  const days = mfaStatus.days_remaining;

  return (
    <Modal visible animationType="slide" transparent onRequestClose={() => setSkipped(true)}>
      <View style={s.backdrop}>
        <View style={s.sheet}>
          <ScrollView contentContainerStyle={s.body} keyboardShouldPersistTaps="handled">
            <Text style={s.title}>Set up two-factor authentication</Text>
            {/* The number is the point. "Required soon" is what people ignore. */}
            <Text style={s.deadline}>
              {days === 1 ? 'Required from tomorrow.' : `Required in ${days} days.`}
            </Text>
            <Text style={s.body_}>
              You can keep working until then, but you will need this to sign in
              afterwards. It takes about a minute.
            </Text>

            <MfaEnrolment onEnrolled={refreshMfaStatus} />

            <TouchableOpacity onPress={() => setSkipped(true)} style={s.skip}>
              <Text style={s.skipText}>Not now</Text>
            </TouchableOpacity>
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.5)' },
  sheet: {
    backgroundColor: c.background, borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg, maxHeight: '85%',
  },
  body:     { padding: spacing.lg, gap: spacing.md },
  title:    { fontSize: fontSize.xl, fontWeight: fontWeight.bold, color: c.foreground },
  deadline: { fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.warning },
  body_:    { fontSize: fontSize.md, color: c.mutedForeground, lineHeight: 22 },
  skip:     { alignItems: 'center', paddingVertical: spacing.md },
  skipText: { color: c.mutedForeground, fontSize: fontSize.md },
});
