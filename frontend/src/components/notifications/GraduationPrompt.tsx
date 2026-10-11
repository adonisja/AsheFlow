import React, { useId, useState } from 'react';
import { GraduationCap, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import InterruptiveDialog from './InterruptiveDialog';
import { useNotificationContext } from '../../contexts/NotificationContext';
import type { Notification } from '../../contexts/NotificationContext';

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
      className="border-emerald-200 dark:border-emerald-900/60"
    >
      {/* The celebratory band is this component's whole visual identity — it is
          what stops a graduation reading like a settings change. */}
      <div className="rounded-t-2xl bg-gradient-to-br from-emerald-500 to-teal-600 px-6 py-7 text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-white/20 ring-1 ring-inset ring-white/30">
          <GraduationCap className="h-7 w-7 text-white" aria-hidden="true" />
        </div>
        <h2 id={titleId} className="mt-3 text-xl font-bold text-white">
          Congratulations — you're a Walker
        </h2>
      </div>

      <div className="px-6 py-5">
        <p className="text-[0.9375rem] leading-relaxed text-slate-700 dark:text-slate-300">
          {notification.message}
        </p>
        <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">
          Your access has already changed. Here's what's different for you now.
        </p>

        {failed && (
          <p
            role="alert"
            className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
          >
            We couldn't record that just now. Try again — this will keep
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
              className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 font-semibold text-white hover:bg-emerald-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 disabled:opacity-60 dark:focus-visible:ring-offset-slate-900"
            >
              {action.label}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => void finish('skipped')}
            className="inline-flex min-h-11 items-center justify-center rounded-xl border border-slate-300 px-4 font-medium text-slate-700 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:opacity-60 dark:border-slate-600 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Later
          </button>
        </div>
      </div>
    </InterruptiveDialog>
  );
}
