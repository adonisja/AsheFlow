import React from 'react';
import { AlertTriangle } from 'lucide-react';

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
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Dialog */}
      <div
        className="relative z-10 w-full max-w-sm rounded-2xl bg-surface border border-border shadow-xl p-6 space-y-4 animate-slide-up"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <div className={`flex items-center justify-center w-9 h-9 rounded-xl bg-accent shrink-0 mt-0.5`}>
            <AlertTriangle className={`w-5 h-5 ${iconColor}`} />
          </div>
          <div className="min-w-0">
            <p className="font-semibold text-foreground">{title}</p>
            <p className="text-sm text-muted-foreground mt-1">{message}</p>
          </div>
        </div>

        <div className="flex gap-3 justify-end pt-1">
          <button
            onClick={onCancel}
            className="btn-ghost text-sm px-4 py-2"
          >
            {cancelLabel}
          </button>
          <button
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
