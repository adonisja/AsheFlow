import React, { useCallback, useEffect, useRef } from 'react';
import { useReducedMotion } from '../../hooks/useReducedMotion';

/** The accessibility contract shared by every interruptive notification (ADR-494 D11).
 *
 *  ## Why a native `<dialog>` and not a div
 *
 *  `showModal()` gives the top layer, `aria-modal`, and inertness of the rest
 *  of the document for free — three things a hand-rolled overlay gets wrong in
 *  ways that only a screen-reader user notices: background content stays
 *  focusable, so Tab walks out of the "modal" into the page behind it.
 *
 *  ## Why GATE blocks Escape and PROMPT does not
 *
 *  A dialog that cannot be dismissed with Escape is normally a WCAG violation.
 *  The documented exception is *"legal notices that require user
 *  acknowledgment through activating a button before closing"*, and a payroll
 *  sign-off is that category.
 *
 *  Claiming an exception means earning it, so the GATE path must give a
 *  *visible* way out — which is why `actions` is required rather than optional
 *  for a gate, and why the server degrades a gate with no action to a prompt
 *  (D6) instead of letting one render here. A gate whose only control is the
 *  one this component hides is the dismiss-only wall the whole ADR removes.
 *
 *  PROMPT keeps Escape. Nothing about a congratulatory notice justifies
 *  trapping anyone.
 */
export interface InterruptiveDialogProps {
  open: boolean;
  /** `gate` blocks Escape and backdrop dismissal; `prompt` allows both. */
  kind: 'gate' | 'prompt';
  /** Used for `aria-labelledby`, so it must be rendered visibly by the child. */
  titleId: string;
  /** Called for any dismissal a PROMPT allows. Never called for a GATE. */
  onDismiss: () => void;
  children: React.ReactNode;
  /** Extra classes on the dialog element, for the per-type visual identity. */
  className?: string;
}

export default function InterruptiveDialog({
  open,
  kind,
  titleId,
  onDismiss,
  children,
  className = '',
}: InterruptiveDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const reduceMotion = useReducedMotion();
  // Whoever had focus when this opened, so it can be given back. Without this,
  // focus lands on <body> after close and a keyboard user restarts from the top
  // of the page — which on a long dispatch list is a real cost, not a nicety.
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (open && !el.open) {
      opener.current = document.activeElement;
      el.showModal();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open]);

  // Return focus on unmount as well as on close — a route change can unmount
  // this while it is still open, and the effect above would never run.
  useEffect(() => () => {
    const prev = opener.current;
    if (prev instanceof HTMLElement && document.contains(prev)) prev.focus();
  }, []);

  const handleCancel = useCallback((e: React.SyntheticEvent<HTMLDialogElement>) => {
    // `cancel` fires for Escape AND for the backdrop on some browsers. A GATE
    // prevents the default, which is what keeps the dialog open; the ADR-494
    // D11 exception is claimed exactly here and nowhere else.
    if (kind === 'gate') {
      e.preventDefault();
      return;
    }
    onDismiss();
  }, [kind, onDismiss]);

  const handleClose = useCallback(() => {
    const prev = opener.current;
    if (prev instanceof HTMLElement && document.contains(prev)) prev.focus();
  }, []);

  return (
    <dialog
      ref={ref}
      aria-modal="true"
      aria-labelledby={titleId}
      onCancel={handleCancel}
      onClose={handleClose}
      // A click on the dialog's own backdrop lands on the dialog element
      // itself, so compare the target. A prompt closes; a gate ignores it.
      onClick={(e) => {
        if (kind === 'gate') return;
        if (e.target === ref.current) onDismiss();
      }}
      className={[
        'm-auto w-[min(32rem,calc(100vw-2rem))] rounded-2xl border p-0',
        'border-border bg-card text-foreground shadow-2xl',
        'backdrop:bg-black/60 backdrop:backdrop-blur-sm',
        reduceMotion ? '' : 'motion-safe:animate-[dialogIn_160ms_ease-out]',
        className,
      ].filter(Boolean).join(' ')}
    >
      {children}
    </dialog>
  );
}
