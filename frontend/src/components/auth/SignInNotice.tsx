/**
 * The one notice the sign-in card shows (ADR-556 D5). Mobile has the same
 * component (mobile/src/screens/Auth/SignInNotice.tsx); keep the two in step.
 *
 * A reset request's result, a setup-closed refusal and every kind of forced
 * sign-out used to be differently styled boxes, one of them a heavy green slab
 * that repeated its own title. Each is now an icon, a title that says what
 * happened, and a body that says what to do. Meaning never rides on colour
 * alone (WCAG 1.4.1): each tone has its own icon, and the title carries the
 * message. A warning is an alert; success and info are polite status messages
 * (WCAG 4.1.3).
 */
import type { ReactNode } from 'react';
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react';

export type NoticeTone = 'success' | 'warning' | 'info';

const TONE = {
  success: { Icon: CheckCircle2, box: 'bg-success/5 border-success/20', disc: 'bg-success/10 text-success' },
  warning: { Icon: AlertTriangle, box: 'bg-warning/5 border-warning/25', disc: 'bg-warning/15 text-warning' },
  info:    { Icon: Info,          box: 'bg-primary/5 border-primary/15', disc: 'bg-primary/10 text-primary' },
} as const;

export default function SignInNotice({ tone, title, children }: {
  tone: NoticeTone; title: string; children: ReactNode;
}) {
  const t = TONE[tone];
  return (
    <div role={tone === 'warning' ? 'alert' : 'status'}
         className={`flex items-start gap-3 rounded-xl border px-4 py-3.5 mb-6 text-sm ${t.box}`}>
      <span className={`mt-0.5 grid place-items-center w-7 h-7 rounded-full shrink-0 ${t.disc}`} aria-hidden="true">
        <t.Icon className="w-4 h-4" />
      </span>
      <div className="min-w-0 space-y-1 pt-1">
        <p className="font-semibold text-foreground leading-snug">{title}</p>
        <div className="text-muted-foreground leading-relaxed space-y-1">{children}</div>
      </div>
    </div>
  );
}
