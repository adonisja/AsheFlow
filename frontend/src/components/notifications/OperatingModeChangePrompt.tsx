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
      className="border-amber-200 dark:border-amber-900/60"
    >
      <div className="flex items-start gap-3 border-b border-slate-200 px-6 py-5 dark:border-slate-700">
        <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 dark:bg-amber-950/50">
          <Settings2 className="h-5 w-5 text-amber-700 dark:text-amber-400" aria-hidden="true" />
        </div>
        <div className="min-w-0">
          <h2 id={titleId} className="text-lg font-bold leading-tight text-slate-900 dark:text-slate-50">
            How this company runs has changed
          </h2>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            Some of what you see and do is different now.
          </p>
        </div>
      </div>

      <div className="px-6 py-5">
        <p className="text-[0.9375rem] leading-relaxed text-slate-700 dark:text-slate-300">
          {notification.message}
        </p>

        {/* Stated plainly rather than discovered. A walker who finds a button
            missing assumes the app is broken; a walker who was told the mode
            changed knows to look at their role page. */}
        <div className="mt-4 flex gap-2.5 rounded-xl bg-slate-50 px-3.5 py-3 dark:bg-slate-800/60">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Pages and buttons you used before may have moved or gone. That is the
            mode change, not a fault.
          </p>
        </div>

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
              className="inline-flex min-h-11 flex-1 items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 font-semibold text-white hover:bg-slate-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-500 focus-visible:ring-offset-2 disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white dark:focus-visible:ring-offset-slate-900"
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
            Not now
          </button>
        </div>
      </div>
    </InterruptiveDialog>
  );
}
