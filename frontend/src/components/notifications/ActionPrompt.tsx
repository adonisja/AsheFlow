import React, { useId, useState } from 'react';
import { ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import InterruptiveDialog from './InterruptiveDialog';
import { useNotificationContext } from '../../contexts/NotificationContext';
import type { Notification } from '../../contexts/NotificationContext';

/** The prompt for every type without a face of its own (ADR-505 D4).
 *
 *  Before this, the host's `switch` had cases only for `graduation` and
 *  `operating_mode_change`, and every other prompt fell to `default: return
 *  null`. `timecard_mismatch` is declared GATE and the server degrades it to a
 *  PROMPT on every day but the last, so the payroll sign-off's whole prompt phase
 *  rendered NOTHING, and, being first in line, hid the prompts queued behind it.
 *  Reproduced on staging 2026-10-13.
 *
 *  Deliberately plain: the registry label as the title, the message, the type's
 *  own action, and "Later". The two types that need an identity of their own
 *  (ADR-494 D5) keep it; this is the floor every other prompt stands on.
 *
 *  "Later" records `skipped`, which re-asks on the next load (ADR-494); the
 *  action records `confirmed`, which settles it (ADR-505 D2).
 */
export default function ActionPrompt({
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

  const finish = async (choice: 'confirmed' | 'skipped', then?: () => void) => {
    setBusy(true);
    setFailed(false);
    try {
      await acknowledge(notification.id, choice, 'prompt');
      then?.();
      onDone();
    } catch {
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
      className="border-border"
    >
      <div className="px-6 pb-5 pt-6">
        <h2 id={titleId} className="text-lg font-bold leading-tight text-foreground">
          {notification.label}
        </h2>
        <p className="mt-3 text-[0.9375rem] leading-relaxed text-foreground">
          {notification.message}
        </p>

        {failed && (
          <p role="alert" className="mt-4 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning">
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
              className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-primary px-4 font-semibold text-primary-foreground hover:bg-primary/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-60"
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
