import React, { useId, useState } from 'react';
import { Settings2, ArrowRight, AlertTriangle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import InterruptiveDialog from './InterruptiveDialog';
import { useNotificationContext } from '../../contexts/NotificationContext';
import type { Notification } from '../../contexts/NotificationContext';

/** "How this company runs has changed" (ADR-494 D5, type `operating_mode_change`).
 *
 *  A separate component from GraduationPrompt, not a shared one with a prop.
 *  D5: *"One parameterised component would make them look alike, and the second
 *  would read as a promotion nobody earned."*
 *
 *  Where graduation is a warm gradient and a seal, this is sober: a neutral
 *  header, an explicit warning strip, and copy that says half the app changed.
 *  Nobody earned this and nobody chose it — it happened to them — so the design
 *  owes them orientation rather than celebration.
 *
 *  A PROMPT, not a gate (D1): the mode already switched, so blocking teaches
 *  dismissal. ADR-305 is why the link matters more than the wall — half the
 *  surface genuinely differs between modes, and the reader needs the
 *  ROLE-SCOPED explanation, which is what /my-role is.
 */
export default function OperatingModeChangePrompt({
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
      className="border-warning/30"
    >
      <div className="flex items-start gap-3 border-b border-border px-6 py-5">
        <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-warning/15">
          <Settings2 className="h-5 w-5 text-warning" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <h2 id={titleId} className="text-lg font-bold leading-tight text-foreground">
            How this company runs has changed
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Some of what you see and do is different now.
          </p>
        </div>
      </div>

      <div className="px-6 py-5">
        <p className="text-[0.9375rem] leading-relaxed text-foreground">
          {notification.message}
        </p>

        {/* Stated plainly rather than discovered. A walker who finds a button
            missing assumes the app is broken; a walker who was told the mode
            changed knows to look at their role page. */}
        <div className="mt-4 flex gap-2.5 rounded-xl bg-surface-muted px-3.5 py-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <p className="text-sm text-muted-foreground">
            Pages and buttons you used before may have moved or gone. That is the
            mode change, not a fault.
          </p>
        </div>

        {failed && (
          <p
            role="alert"
            className="mt-4 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning"
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
            Not now
          </button>
        </div>
      </div>
    </InterruptiveDialog>
  );
}
