import React from 'react';
import { AlertCircle } from 'lucide-react';
import { useErrorBanner } from '../../hooks/useErrorBanner';

interface Props {
  message: string | null;
  className?: string;
}

/**
 * The page's error banner — and, since ADR-339, the thing that brings itself to
 * whoever caused the error.
 *
 * ADR-333 found the failure on DispatchDashboard: a correct 409 ("HUB has no
 * dock assigned. Set a bay before publishing.") rendered ~540 lines above the
 * button that caused it, several screens out of view, and was reported as a
 * silent failure. The error was displayed. It was not seen, and to a user those
 * are the same event.
 *
 * The scroll lives HERE rather than in each page because this component is
 * already used by 32 pages. Putting it in the shared component gives every one
 * of them the behaviour with no per-page edit — and, more importantly, means
 * the 33rd page cannot be built without it.
 */
export default function ErrorBanner({ message, className }: Props) {
  // Hooks must run unconditionally — the early return below is AFTER this.
  const ref = useErrorBanner(message);

  if (!message) return null;
  return (
    <div
      ref={ref}
      className={`rounded-lg border border-danger/50 bg-danger/10 p-4 flex gap-3 text-danger${className ? ` ${className}` : ''}`}
    >
      <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
      <p className="text-sm font-medium">{message}</p>
    </div>
  );
}
