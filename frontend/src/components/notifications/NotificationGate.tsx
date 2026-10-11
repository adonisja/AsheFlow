import React, { useId, useState } from 'react';
import { ShieldAlert, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import InterruptiveDialog from './InterruptiveDialog';
import { useNotificationContext } from '../../contexts/NotificationContext';
import type { Notification } from '../../contexts/NotificationContext';

/** The one interruptive surface with no exit but its own action (ADR-494).
 *
 *  Two types reach here, and only two: `credentials_sent` (no app without the
 *  credentials, and nothing to escalate toward) and `timecard_mismatch` inside
 *  the final day before its pay period closes. Everything else the registry
 *  used to gate is now a PROMPT.
 *
 *  ## This component does not decide anything
 *
 *  Whether a gate is a gate is the SERVER's answer (D6): `channels` either
 *  carries `gate` or it does not, and this renders what arrives. The clients
 *  implement no downgrade rule, so they cannot disagree about one — which is
 *  the drift the D4 mobile pass spent a session closing.
 *
 *  So there is deliberately no `if (expired)` or `if (deadlineFar)` here. If
 *  this is on screen, the server decided it should be.
 *
 *  ## Why Escape is blocked, and what that obliges
 *
 *  Blocking Escape is a WCAG exception claimed under *"legal notices that
 *  require user acknowledgment through activating a button before closing"*
 *  (D11). A payroll sign-off is that category. The exception is only earned if
 *  a visible button is genuinely available, which is why `actions` being empty
 *  renders the degraded form below rather than a wall with nothing on it.
 */
export default function NotificationGate({
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

  /** A GATE whose action is missing is the dismiss-only wall this ADR removes.
   *
   *  The server should never send one — D6 degrades it to a prompt first — so
   *  reaching this means the registry declared a GATE with no action and the
   *  server's checks did not catch it. Rendering an acknowledgeable card rather
   *  than a trap is the safe failure: `unavailable` is recorded, which is a
   *  truthful statement that nobody was offered a choice, and distinctly NOT
   *  `skipped`, which would assert a decision that was never presented.
   */
  const degraded = !action;

  const finish = async (choice: 'confirmed' | 'unavailable', then?: () => void) => {
    setBusy(true);
    setFailed(false);
    try {
      await acknowledge(notification.id, choice, 'gate');
      then?.();
      onDone();
    } catch {
      // A gate must NOT close on a failed acknowledgement. The whole point is
      // that the record exists; dismissing without it would let the person
      // through while leaving nothing to show they answered.
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <InterruptiveDialog
      open
      kind="gate"
      titleId={titleId}
      onDismiss={() => { /* unreachable: a gate ignores Escape and backdrop */ }}
      className="border-rose-200 dark:border-rose-900/60"
    >
      <div className="flex items-start gap-3 border-b border-rose-100 bg-rose-50/60 px-6 py-5 dark:border-rose-900/40 dark:bg-rose-950/30">
        <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rose-100 dark:bg-rose-950/60">
          <ShieldAlert className="h-5 w-5 text-rose-700 dark:text-rose-400" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <h2 id={titleId} className="text-lg font-bold leading-tight text-slate-900 dark:text-slate-50">
            {notification.label}
          </h2>
          <p className="mt-0.5 text-sm text-rose-700 dark:text-rose-400">
            This needs an answer before you carry on.
          </p>
        </div>
      </div>

      <div className="px-6 py-5">
        <p className="text-[0.9375rem] leading-relaxed text-slate-700 dark:text-slate-300">
          {notification.message}
        </p>

        {failed && (
          <p
            role="alert"
            className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
          >
            We couldn't record your answer. Try again — this stays until it saves.
          </p>
        )}

        <div className="mt-5">
          {degraded ? (
            /* No action to offer. Acknowledge as `unavailable` and let them
               through, rather than trapping someone behind a control that does
               not exist. */
            <button
              type="button"
              disabled={busy}
              onClick={() => void finish('unavailable')}
              className="inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-slate-900 px-4 font-semibold text-white hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 focus-visible:ring-offset-2 disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:focus-visible:ring-offset-slate-900"
            >
              I've read this
            </button>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => void finish('confirmed', () => navigate(action.route))}
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-rose-600 px-4 font-semibold text-white hover:bg-rose-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-500 focus-visible:ring-offset-2 disabled:opacity-60 dark:focus-visible:ring-offset-slate-900"
            >
              {action.label}
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </div>
      </div>
    </InterruptiveDialog>
  );
}
