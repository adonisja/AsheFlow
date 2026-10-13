import React from 'react';
import { Modal, ScrollView, View, StyleSheet, AccessibilityInfo } from 'react-native';
import { useColors } from '@contexts/ThemeContext';
import { spacing, radius, type ThemeColors } from '@theme/index';
import { useReducedMotionState } from '@hooks/useReducedMotionState';

/**
 * The accessibility contract shared by every interruptive notification on
 * mobile (ADR-494 D11). Twin of `frontend/src/components/notifications/
 * InterruptiveDialog.tsx`.
 *
 * ## The Escape analogue is `onRequestClose`
 *
 * Web claims a WCAG exception by blocking the Escape key on a GATE. On mobile
 * the equivalent gesture is the **Android hardware back button**, which React
 * Native delivers as `Modal.onRequestClose`. A gate must not close on it, for
 * the same reason and with the same obligation: the exception is only earned if
 * a visible button is genuinely available, which is why the server degrades a
 * gate with no action to a prompt (D6) rather than letting one render here.
 *
 * iOS has no hardware back, so there the gate is already modal — but the
 * handler must still be inert, because `onRequestClose` is also what the
 * accessibility escape gesture invokes.
 *
 * ## What differs from the web twin, and why
 *
 * - No focus management. RN has no document focus model; `accessibilityViewIsModal`
 *   is the platform's equivalent and does the same job — it hides everything
 *   behind the sheet from the screen reader, which is what web gets from
 *   `showModal()`'s inertness.
 * - `animationType` is 'none' under reduced motion rather than a CSS guard.
 *   `useReducedMotionState` is the state-returning hook from the D4 pass,
 *   deliberately separate from `primitives.useReduceMotion` which returns a ref
 *   (a state version there caused a "Rendered more hooks than during the
 *   previous render" crash in CompanyStandingCard).
 */
export default function InterruptiveSheet({
  kind,
  onDismiss,
  children,
}: {
  /** `gate` ignores the back button and the backdrop; `prompt` honours both. */
  kind: 'gate' | 'prompt';
  /** Called for any dismissal a PROMPT allows. Never called for a GATE. */
  onDismiss: () => void;
  children: React.ReactNode;
}) {
  const c = useColors();
  const s = styles(c);
  const reduceMotion = useReducedMotionState();

  // Announced on mount. A sheet that appears silently is a sheet a screen
  // reader user does not know has taken over the screen.
  React.useEffect(() => {
    AccessibilityInfo.announceForAccessibility(
      kind === 'gate'
        ? 'This needs an answer before you can carry on.'
        : 'A notice about your account.',
    );
  }, [kind]);

  return (
    <Modal
      visible
      transparent
      animationType={reduceMotion ? 'none' : 'slide'}
      // A GATE deliberately does nothing here. This is the ADR-494 D11
      // exception being claimed, and it is claimed in exactly one place.
      onRequestClose={() => { if (kind !== 'gate') onDismiss(); }}
      // The RN equivalent of showModal()'s inertness: everything behind the
      // sheet is hidden from assistive tech.
      accessibilityViewIsModal
    >
      <View style={s.backdrop}>
        <View style={s.sheet} accessibilityViewIsModal>
          <ScrollView
            contentContainerStyle={s.body}
            keyboardShouldPersistTaps="handled"
          >
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const styles = (c: ThemeColors) => StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.55)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: c.surface,
    borderTopLeftRadius: radius['2xl'],
    borderTopRightRadius: radius['2xl'],
    maxHeight: '88%',
  },
  body: { padding: spacing.lg, paddingBottom: spacing.xl },
});
