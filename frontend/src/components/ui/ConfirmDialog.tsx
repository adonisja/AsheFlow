import React, { useCallback, useEffect, useRef } from 'react';
import { AlertTriangle } from 'lucide-react';

/**
 * Confirmation dialog.
 *
 * A modal is the one component where missing semantics makes the app genuinely
 * UNUSABLE rather than merely worse: with no focus trap a keyboard user tabs
 * straight out into the page behind it, and with no Escape handler there is no
 * way back out without a mouse. This had none of it, across 8 call sites.
 *
 * Handled here so callers cannot forget:
 *  - role="dialog" + aria-modal, labelled by its own title and message.
 *  - Focus moves INTO the dialog on open and RETURNS to the trigger on close.
 *  - Tab is trapped between the buttons.
 *  - Escape cancels.
 *  - The backdrop is aria-hidden — decoration, not content.
 */

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'warning' | 'default';
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'default',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement;
    // Focus CANCEL, not confirm: this dialog is used for deletes, and a
    // destructive action should never be one stray Enter away.
    cancelRef.current?.focus();
    return () => { (returnFocusRef.current as HTMLElement | null)?.focus?.(); };
  }, [open]);

  const onKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.stopPropagation(); onCancel(); return; }
    if (e.key !== 'Tab') return;

    const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (!focusable?.length) return;
    const first = focusable[0];
    const last  = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }, [onCancel]);

  if (!open) return null;

  const confirmClass =
    variant === 'danger'  ? 'bg-danger text-white hover:bg-danger/90' :
    variant === 'warning' ? 'bg-warning text-white hover:bg-warning/90' :
    'btn-primary';

  const iconColor =
    variant === 'danger'  ? 'text-danger' :
    variant === 'warning' ? 'text-warning' :
    'text-primary';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onCancel}
      onKeyDown={onKeyDown}
    >
      {/* Backdrop — decoration, not content. */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" aria-hidden="true" />

      {/* Dialog */}
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        className="relative z-10 w-full max-w-sm rounded-2xl bg-surface border border-border shadow-xl p-6 space-y-4 animate-slide-up"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <div className={`flex items-center justify-center w-9 h-9 rounded-xl bg-accent shrink-0 mt-0.5`}>
            {/* Decorative: the variant is already stated by the text. */}
            <AlertTriangle className={`w-5 h-5 ${iconColor}`} aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <p id="confirm-dialog-title" className="font-semibold text-foreground">{title}</p>
            <p id="confirm-dialog-message" className="text-sm text-muted-foreground mt-1">{message}</p>
          </div>
        </div>

        <div className="flex gap-3 justify-end pt-1">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="btn-ghost text-sm px-4 py-2"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`text-sm px-4 py-2 rounded-xl font-semibold transition-colors ${confirmClass}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
