/**
 * The authenticator setup key, made so nobody retypes it (ADR-557). Mobile has
 * the same idea in mobile/src/components/SetupKey.tsx.
 *
 * On a desktop the QR code stays the primary path. This is for the case the
 * QR can't serve: someone enrolling ON the phone that holds the authenticator
 * (web is used on phones). "Open in authenticator app" is the otpauth:// link
 * the QR already encodes; "Copy" copies the raw key, shown grouped in fours.
 */
import { useEffect, useRef, useState } from 'react';
import { Check, Copy, ExternalLink } from 'lucide-react';

export function groupKey(secret: string): string {
  return secret.replace(/\s+/g, '').replace(/(.{4})(?=.)/g, '$1 ');
}

export default function SetupKey({ secret, uri }: { secret: string; uri: string | null }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(secret.replace(/\s+/g, ''));
      setCopied(true); setFailed(false);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      // No clipboard permission (insecure context, old browser): the key is
      // still selectable text, so say so rather than fail silently.
      setFailed(true);
    }
  };

  return (
    <div className="space-y-2 text-left">
      {uri && (
        <a href={uri}
           className="flex items-center justify-center gap-2 w-full rounded-lg border border-border px-3 py-2 text-sm font-medium text-primary hover:bg-accent transition-colors">
          <ExternalLink className="w-4 h-4" aria-hidden="true" />
          On this phone? Open in your authenticator app
        </a>
      )}
      <p className="text-xs text-muted-foreground">Or add it by hand with this key:</p>
      <div className="flex items-center gap-2 rounded-lg bg-accent pl-3 pr-1.5 py-1.5">
        <code className="flex-1 min-w-0 font-mono text-sm text-foreground break-all select-all">{groupKey(secret)}</code>
        <button type="button" onClick={copy}
                aria-label={copied ? 'Key copied' : 'Copy key'}
                className="shrink-0 inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2.5 py-1.5 text-xs font-semibold text-primary hover:bg-surface-muted transition-colors">
          {copied ? <Check className="w-3.5 h-3.5" aria-hidden="true" /> : <Copy className="w-3.5 h-3.5" aria-hidden="true" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      {failed && <p className="text-xs text-warning">Couldn't copy here. Select the key and copy it instead.</p>}
    </div>
  );
}
