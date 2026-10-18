import React, { useState } from 'react';
import { AlertTriangle, ShieldCheck } from 'lucide-react';

/**
 * ADR-538 — the company setup window: while 10 or fewer people have a sign-in
 * account and the company is within 30 days of creation, existing (already
 * trained) staff can be added at their current role. Inside the window the
 * system cannot tell an experienced worker from a brand-new hire, so the person
 * granting roles must review them — and sign off before the preview step. The
 * server refuses a window-only grant without that sign-off; this is the UI half.
 *
 * One file so the banner, the disclaimer and the sign-off say the same thing on
 * the invite form and the bulk import.
 */
export interface SetupWindow {
  open: boolean;
  registered: number;
  limit: number;
  days_left: number;
  closes_at: string | null;
}

const RULE =
  'New hires must start as Trainee or Driver Trainee. Experienced staff joining ' +
  'with the company can keep their current role (Walker, Trainer, Driver, Captain ' +
  'or Field Supervisor).';

export function SetupWindowBanner({ w }: { w: SetupWindow }) {
  return (
    <div role="status" className="flex items-start gap-3 rounded-xl border-2 border-warning/50 bg-warning/10 px-4 py-3 text-sm">
      <AlertTriangle className="w-5 h-5 text-warning shrink-0 mt-0.5" />
      <div className="space-y-1">
        <p className="font-semibold text-foreground">
          Company setup window open — {w.registered} of {w.limit} sign-ups · {w.days_left} day{w.days_left === 1 ? '' : 's'} left
        </p>
        <p className="text-muted-foreground">
          {RULE} Review every role carefully. The window closes after the {w.limit + 1}th sign-up or
          30 days, whichever comes first; after that, roles are earned through training and promotion.
        </p>
      </div>
    </div>
  );
}

export function RoleReviewDisclaimer() {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2.5 text-sm">
      <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />
      <p className="text-foreground">
        <span className="font-semibold">Check every role before you send.</span> {RULE}
      </p>
    </div>
  );
}

/** The sign-off step shown BEFORE the preview/review step while the window is open. */
export function RoleSignOff({ onConfirm, onBack, what }: {
  onConfirm: () => void;
  onBack: () => void;
  what: 'invite' | 'import';
}) {
  const [checked, setChecked] = useState(false);
  return (
    <div className="p-6 space-y-5">
      <div className="flex items-start gap-3">
        <ShieldCheck className="w-6 h-6 text-warning shrink-0" />
        <div className="space-y-2">
          <h3 className="font-semibold text-foreground">Sign off on roles before you continue</h3>
          <p className="text-sm text-muted-foreground">
            This company is in its setup window, so {what === 'import' ? 'these people' : 'this person'} can
            be added at {what === 'import' ? 'their' : 'their'} current role without training. That is only
            right for experienced staff joining with the company.
          </p>
          <ul className="text-sm text-foreground list-disc pl-5 space-y-1">
            <li>Brand-new hires: <span className="font-medium">Trainee</span> (walkers) or <span className="font-medium">Driver Trainee</span> (drivers).</li>
            <li>Experienced staff: the role they hold today.</li>
          </ul>
          <p className="text-xs text-muted-foreground">Your sign-off is recorded with your name.</p>
        </div>
      </div>
      <label className="flex items-start gap-3 rounded-xl border border-border px-4 py-3 cursor-pointer hover:bg-accent/30">
        <input type="checkbox" className="mt-1" checked={checked} onChange={e => setChecked(e.target.checked)} />
        <span className="text-sm text-foreground">
          I have reviewed every role. New hires are Trainee or Driver Trainee; experienced staff keep their current role.
        </span>
      </label>
      <div className="flex justify-end gap-3">
        <button type="button" onClick={onBack} className="btn-ghost">Back</button>
        <button type="button" onClick={onConfirm} disabled={!checked} className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed">
          Sign off and continue
        </button>
      </div>
    </div>
  );
}
