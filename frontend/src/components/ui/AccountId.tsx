/**
 * An account's permanent ID, short and copyable (ADR-550 D1).
 *
 * Names repeat and emails change; this is what identifies the account to an
 * action -- the surveyor ID for a surveyor, the Cognito sub for platform staff.
 * Shown as its first 8 characters (enough to tell accounts apart on a page),
 * with the full value on hover and one tap to copy it whole. Copy degrades to
 * "select it yourself" when the clipboard is unavailable or denied.
 */
import { useState } from 'react';
import { Check, Copy } from 'lucide-react';

export default function AccountId({ id, label = 'ID' }: { id: string | null | undefined; label?: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  if (!id) return null;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setState('copied');
    } catch {
      setState('failed');
    }
    setTimeout(() => setState('idle'), 1600);
  };
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      {label && <span>{label}</span>}
      <code className="font-mono text-foreground select-all" title={id}>{id.slice(0, 8)}</code>
      <button type="button" onClick={copy} aria-label={`Copy the full ${label || 'ID'}`}
              className="inline-flex items-center justify-center w-6 h-6 rounded hover:bg-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">
        {state === 'copied' ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
      </button>
      {state === 'failed' && <span role="status">Select it to copy</span>}
      {state === 'copied' && <span role="status" className="sr-only">Copied</span>}
    </span>
  );
}
