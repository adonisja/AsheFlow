import React, { useEffect, useId, useState } from 'react';
import { GraduationCap, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import InterruptiveDialog from './InterruptiveDialog';
import { useNotificationContext } from '../../contexts/NotificationContext';
import type { Notification } from '../../contexts/NotificationContext';
import axiosClient from '../../api/axiosClient';
import { roleLabel } from '../../utils/roleLabels';

/** "You passed" (ADR-494 D5, type `graduation`).
 *
 *  Deliberately NOT the same component as OperatingModeChangePrompt, and not a
 *  parameterised one. D5: *"`graduation` is congratulatory;
 *  `operating_mode_change` is 'half your app changed'. One parameterised
 *  component would make them look alike, and the second would read as a
 *  promotion nobody earned."*
 *
 *  So this one is warm — a seal, the person's new title, a single forward
 *  action — and the mode-change one is sober. The shared part is the
 *  accessibility shell and the acknowledgement call, which is the part that
 *  must not differ.
 *
 *  A PROMPT, not a gate: the permissions already took effect, so proceeding is
 *  uninformed rather than wrong, and the remedy for uninformed is a link.
 */
export default function GraduationPrompt({
  notification,
  onDone,
}: {
  notification: Notification;
  onDone: () => void;
}) {
  const titleId = useId();
  const navigate = useNavigate();
  const { acknowledge } = useNotificationContext();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const action = notification.actions[0];

  // ADR-505 D5. The title names the role the person actually holds now. It was
  // hardcoded "Walker", which is right only while trainee -> walker is the sole
  // promotion that raises this. The role is set BEFORE the notification is
  // raised, so /employees/me already reports the new one.
  const [role, setRole] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    axiosClient.get<{ role: string }>('/employees/me')
      .then(r => { if (live) setRole(r.data.role); })
      .catch(() => { /* keep the role-free title */ });
    return () => { live = false; };
  }, []);

  const finish = async (
    choice: 'confirmed' | 'skipped',
    then?: () => void,
  ) => {
    setBusy(true);
    setFailed(false);
    try {
      await acknowledge(notification.id, choice, 'prompt');
      then?.();
      onDone();
    } catch {
      // The record did not land. Keep the sheet open and say so rather than
      // dismissing: a silently lost acknowledgement means this reappears next
      // launch with no explanation, which reads as a broken app.
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <InterruptiveDialog
      open
      kind="prompt"
      titleId={titleId}
      onDismiss={() => void finish('skipped')}
      className="border-success/30"
    >
      {/* The celebratory band is this component's whole visual identity — it is
          what stops a graduation reading like a settings change. */}
      <div className="rounded-t-2xl bg-gradient-to-br from-success to-teal px-6 py-7 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-success-foreground/20 ring-1 ring-inset ring-success-foreground/30">
          <GraduationCap className="h-7 w-7 text-success-foreground" aria-hidden="true" />
        </div>
        <h2 id={titleId} className="mt-3 text-xl font-bold text-success-foreground">
          {role ? `Congratulations, you're a ${roleLabel(role)}` : 'Congratulations on your new role'}
        </h2>
      </div>

      <div className="px-6 py-5">
        {/* ADR-505 D5, a first pass before the owner's visual triage: the
            notification's own message is the subtitle; our explanation is the
            body. */}
        <p className="text-sm leading-relaxed text-muted-foreground">
          {notification.message}
        </p>
        <p className="mt-3 text-[0.9375rem] leading-relaxed text-foreground">
          Your new access is already on. See what's changed for you.
        </p>

        {failed && (
          <p
            role="alert"
            className="mt-4 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning"
          >
            We couldn't record that just now. Try again. This will keep
            appearing until it saves.
          </p>
        )}

        <div className="mt-5 flex flex-col gap-2 sm:flex-row-reverse">
          {action && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void finish('confirmed', () => navigate(action.route))}
              /* min-h-11 is the 44px floor D11 requires. A walker taps this in
                 a van, not with a mouse. */
              className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-success px-4 font-semibold text-success-foreground hover:bg-success/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-success focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-60"
            >
              {action.label}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => void finish('skipped')}
            className="inline-flex min-h-11 items-center justify-center rounded-xl border border-border-strong px-4 font-medium text-foreground hover:bg-surface-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
          >
            Later
          </button>
        </div>
      </div>
    </InterruptiveDialog>
  );
}
