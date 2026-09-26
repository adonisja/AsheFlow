import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { CheckCircle2, Lock, Phone, Hash, AlertCircle, HelpCircle, Pencil } from 'lucide-react';
import SettingsHelpDrawer from '../components/ui/SettingsHelpDrawer';

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1';

type TokenInfo = {
  employee_id: string;
  name: string;
  email: string;
  role: string;
  phone_last4: string | null;
};

type DoneInfo = { username: string };

function formatUSPhone(raw: string): string {
  const digits = raw.replace(/\D/g, '').slice(0, 10);
  if (digits.length === 0) return '';
  if (digits.length <= 3)  return `(${digits}`;
  if (digits.length <= 6)  return `(${digits.slice(0, 3)}) ${digits.slice(3)}`;
  return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
}

function isValidUSPhone(raw: string): boolean {
  return raw.replace(/\D/g, '').length === 10;
}

function toE164Phone(formatted: string): string {
  const digits = formatted.replace(/\D/g, '');
  return digits.length === 10 ? `+1${digits}` : formatted;
}

/**
 * Role chip colours, from the generated token layer (ADR-254).
 *
 * These were raw Tailwind literals (`bg-amber-100`) that mapped trainee->amber
 * and trainer->violet — the exact INVERSE of the token palette, so a trainer
 * saw violet while registering and amber everywhere after signing in. Inline
 * `hsl(var(--token))` matches `components/ui/Avatar.tsx`, which is the pattern
 * the rest of the app's role colouring already uses.
 *
 * The role name renders as text inside the chip, so colour is never the sole
 * carrier of meaning — see the usage rule on `getRoleColor` in mobile theme.
 */
const ROLE_COLORS: Record<string, { background: string; color: string }> = {
  driver:  { background: 'hsl(var(--driver) / 0.15)',  color: 'hsl(var(--driver))'  },
  walker:  { background: 'hsl(var(--walker) / 0.15)',  color: 'hsl(var(--walker))'  },
  trainer: { background: 'hsl(var(--trainer) / 0.15)', color: 'hsl(var(--trainer))' },
  trainee: { background: 'hsl(var(--trainee) / 0.15)', color: 'hsl(var(--trainee))' },
};

export default function Register() {
  const [params]  = useSearchParams();
  const navigate  = useNavigate();
  const token     = params.get('token') ?? '';

  const [tokenInfo,  setTokenInfo]  = useState<TokenInfo | null>(null);
  const [tokenError, setTokenError] = useState('');
  const [validating, setValidating] = useState(true);

  const [discordId,  setDiscordId]  = useState('');
  const [phone,      setPhone]      = useState('');
  const [fieldError, setFieldError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done,       setDone]       = useState<DoneInfo | null>(null);

  // 'form' | 'review'
  const [step, setStep] = useState<'form' | 'review'>('form');

  // The shared help drawer, as on Company Settings, Preferences and Crew Pins.
  // This page had its own popover, which was the only hand-rolled help
  // affordance left in the app.
  const [helpKey, setHelpKey] = useState<string | null>(null);

  const handlePhoneChange = (v: string) => {
    setPhone(formatUSPhone(v));
    setFieldError('');
  };

  useEffect(() => {
    if (!token) {
      setTokenError('No invite token found. Check your email for the correct link.');
      setValidating(false);
      return;
    }
    fetch(`${API_BASE}/registration/validate?token=${encodeURIComponent(token)}`)
      .then(async res => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.detail ?? 'Invalid or expired invite link.');
        }
        return res.json() as Promise<TokenInfo>;
      })
      .then(info => { setTokenInfo(info); setValidating(false); })
      .catch(err  => { setTokenError(err.message); setValidating(false); });
  }, [token]);

  const handleFormNext = (e: React.FormEvent) => {
    e.preventDefault();
    setFieldError('');

    if (!discordId.trim()) {
      setFieldError('Discord ID is required.');
      return;
    }
    if (!/^\d{17,20}$/.test(discordId.trim())) {
      setFieldError('Discord ID must be a numeric snowflake (17-20 digits). Enable Developer Mode in Discord, then right-click your profile → Copy User ID.');
      return;
    }
    if (!isValidUSPhone(phone)) {
      setFieldError('Enter a valid 10-digit US phone number.');
      return;
    }
    const digits = phone.replace(/\D/g, '');
    if (tokenInfo?.phone_last4 && !digits.endsWith(tokenInfo.phone_last4)) {
      setFieldError(`Phone number doesn't match. It should end in ···${tokenInfo.phone_last4}.`);
      return;
    }

    setStep('review');
  };

  const handleConfirm = async () => {
    setFieldError('');
    setSubmitting(true);
    try {
      const res = await fetch(`${API_BASE}/registration/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          token,
          discord_id:   discordId.trim(),
          phone_number: toE164Phone(phone),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail ?? 'Registration failed.');
      setDone({ username: body.username });
    } catch (err: any) {
      setFieldError(err.message);
      setStep('form');
    } finally {
      setSubmitting(false);
    }
  };

  // ── Loading ───────────────────────────────────────────────────────────────
  if (validating) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-sm text-muted-foreground">Validating invite link…</p>
        </div>
      </div>
    );
  }

  // ── Invalid token ─────────────────────────────────────────────────────────
  if (tokenError) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4">
        <div className="max-w-sm w-full text-center space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-danger/10 flex items-center justify-center mx-auto">
            <AlertCircle className="w-7 h-7 text-danger" />
          </div>
          <h1 className="text-xl font-bold text-foreground">Invalid invite link</h1>
          <p className="text-sm text-muted-foreground">{tokenError}</p>
        </div>
      </div>
    );
  }

  // ── Done screen ───────────────────────────────────────────────────────────
  if (done) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4">
        <div className="max-w-sm w-full space-y-6 text-center">
          <div className="w-16 h-16 rounded-2xl bg-success/10 flex items-center justify-center mx-auto">
            <CheckCircle2 className="w-8 h-8 text-success" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">You're all set!</h1>
            <p className="text-sm text-muted-foreground mt-1">Your account has been created.</p>
          </div>

          <div className="card p-4 text-left space-y-2">
            <p className="text-sm text-foreground">
              An email has been sent to <span className="font-semibold">{tokenInfo!.email}</span> with your username and a temporary password.
            </p>
            <p className="text-xs text-muted-foreground">
              Open that email, then return here to sign in. You'll be prompted to set a new password on first login.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ── Shared layout wrapper ─────────────────────────────────────────────────
  const roleChipStyle = ROLE_COLORS[tokenInfo!.role]
    ?? { background: 'hsl(var(--neutral) / 0.15)', color: 'hsl(var(--neutral))' };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 py-12">
      <div className="w-full max-w-md space-y-6 animate-slide-up">

        {/* Brand mark */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-primary shadow-lg shadow-primary/30 mx-auto">
            <span className="text-primary-foreground text-xl font-extrabold tracking-tight">AF</span>
          </div>
          <div>
            <h1 className="text-2xl font-extrabold text-foreground tracking-tight">AsheFlow</h1>
            <p className="text-sm text-muted-foreground">Field operations, simplified</p>
          </div>
        </div>

        {/* Card */}
        <div className="card p-0 overflow-hidden">
          {/* Card header stripe */}
          <div className="bg-accent/50 border-b border-border px-6 py-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="text-lg font-bold text-foreground tracking-tight truncate">
                  Welcome, {tokenInfo!.name}.
                </h2>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {step === 'form'
                    ? 'Two details to add, then you are in.'
                    : 'Check these, then submit.'}
                </p>
              </div>
              {/* A two-step flow said so nowhere, so "Review & Confirm" arrived
                  as a surprise second page. Dots rather than a bar: there are
                  two steps and a bar for two steps is a decoration. */}
              <div className="flex items-center gap-1.5 shrink-0 pt-1.5" aria-hidden>
                <span className={`w-6 h-1.5 rounded-full transition-colors ${
                  step === 'form' ? 'bg-primary' : 'bg-success'}`} />
                <span className={`w-6 h-1.5 rounded-full transition-colors ${
                  step === 'review' ? 'bg-primary' : 'bg-border'}`} />
              </div>
            </div>
            <p className="sr-only">
              {step === 'form' ? 'Step 1 of 2: your details' : 'Step 2 of 2: review'}
            </p>
          </div>

          <div className="px-6 py-5 space-y-5">
            {/* Locked info (always visible) */}
            <div className="rounded-xl border border-border bg-accent/30 overflow-hidden">
              <div className="flex items-center gap-1.5 px-4 pt-3 pb-1">
                <Lock className="w-3 h-3 text-muted-foreground shrink-0" />
                <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  From your invite
                </span>
              </div>
              <div className="divide-y divide-border">
              {[
                { label: 'Name',  value: tokenInfo!.name },
                { label: 'Email', value: tokenInfo!.email },
                { label: 'Role',  value: (
                  <span
                    className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold capitalize"
                    style={roleChipStyle}
                  >
                    {tokenInfo!.role}
                  </span>
                )},
              ].map(({ label, value }) => (
                <div key={label} className="flex items-center justify-between gap-3 px-4 py-2.5">
                  <span className="text-xs text-muted-foreground shrink-0">{label}</span>
                  <span className="text-sm font-medium text-foreground truncate">{value}</span>
                </div>
              ))}
              </div>
            </div>

            {/* ── STEP 1: Form ── */}
            {step === 'form' && (
              <form onSubmit={handleFormNext} className="space-y-4">

                {/* Discord ID */}
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5">
                    {/* "Discord ID" alone is ambiguous: the company also has a
                        server (guild) ID, and a new Owner has just been told to
                        set one up. Say whose. */}
                    <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      Your Discord User ID <span className="text-danger">*</span>
                    </label>
                    <button
                      type="button"
                      onClick={() => setHelpKey('discord_user_id')}
                      className="inline-flex items-center gap-1 -my-1 px-1.5 py-1 rounded-md
                                 text-[11px] font-medium text-primary hover:bg-primary/10
                                 focus-visible:outline-none focus-visible:ring-2
                                 focus-visible:ring-primary/40 transition-colors"
                      aria-label="How to find your Discord user ID"
                    >
                      <HelpCircle className="w-3.5 h-3.5" />
                      Where do I find this?
                    </button>
                  </div>
                  <div className="flex items-stretch rounded-xl border border-border bg-input overflow-hidden focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all">
                    <span className="flex items-center px-3 text-muted-foreground bg-accent/60 border-r border-border shrink-0">
                      <Hash className="w-4 h-4" />
                    </span>
                    <input
                      type="text"
                      value={discordId}
                      onChange={e => { setDiscordId(e.target.value); setFieldError(''); }}
                      placeholder="e.g. 123456789012345678"
                      autoCapitalize="none"
                      autoCorrect="off"
                      required
                      className="flex-1 px-3 py-2.5 bg-transparent text-sm text-foreground focus:outline-none"
                    />
                  </div>
                  {discordId.trim() && !/^\d{17,20}$/.test(discordId.trim()) && (
                    <p className="text-xs text-danger">Must be a numeric snowflake ID (17-20 digits only).</p>
                  )}
                </div>

                {/* Phone */}
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    Phone number <span className="text-danger">*</span>
                  </label>
                  <div className="flex items-stretch rounded-xl border border-border bg-input overflow-hidden focus-within:ring-2 focus-within:ring-primary/30 focus-within:border-primary/50 transition-all">
                    <span className="flex items-center gap-1.5 px-3 text-sm font-semibold text-muted-foreground bg-accent/60 border-r border-border select-none shrink-0">
                      <Phone className="w-3.5 h-3.5" /> +1
                    </span>
                    <input
                      type="tel"
                      value={phone}
                      onChange={e => handlePhoneChange(e.target.value)}
                      placeholder="(555) 000-0000"
                      required
                      className="flex-1 px-3 py-2.5 bg-transparent text-sm text-foreground focus:outline-none"
                    />
                  </div>
                  {tokenInfo!.phone_last4 ? (
                    <p className="text-xs text-subtle">
                      Must match the number on file ending in{' '}
                      <span className="font-mono font-semibold text-foreground">···{tokenInfo!.phone_last4}</span>.
                    </p>
                  ) : (
                    /* No number was on file, so nothing is being matched.
                       The old copy promised "account verification", which is
                       not what this branch does (ADR-457 D3). */
                    <p className="text-xs text-subtle">How your company reaches you.</p>
                  )}
                </div>

                {fieldError && (
                  <div className="flex items-start gap-2 rounded-xl bg-danger/10 border border-danger/20 px-3 py-2.5">
                    <AlertCircle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
                    <p className="text-sm text-danger">{fieldError}</p>
                  </div>
                )}

                <button
                  type="submit"
                  className="btn-primary w-full py-2.5 flex items-center justify-center gap-2"
                >
                  Review &amp; Confirm
                </button>
              </form>
            )}

            {/* ── STEP 2: Review ── */}
            {step === 'review' && (
              <div className="space-y-4">
                {/* Review card */}
                <div className="rounded-xl border border-border overflow-hidden">
                  <div className="px-4 py-2.5 bg-accent/40 border-b border-border">
                    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Your information</p>
                  </div>
                  <div className="divide-y divide-border">
                    <div className="flex items-center justify-between px-4 py-3">
                      <span className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Hash className="w-3.5 h-3.5" /> Discord user ID
                      </span>
                      <span className="font-mono text-sm font-semibold text-foreground">{discordId.trim()}</span>
                    </div>
                    <div className="flex items-center justify-between px-4 py-3">
                      <span className="flex items-center gap-2 text-xs text-muted-foreground">
                        <Phone className="w-3.5 h-3.5" /> Phone
                      </span>
                      <span className="text-sm font-semibold text-foreground">+1 {phone}</span>
                    </div>
                  </div>
                </div>

                <p className="text-xs text-center text-muted-foreground">
                  Double-check your details above. Once submitted, your account will be created and credentials sent to <span className="font-medium text-foreground">{tokenInfo!.email}</span>.
                </p>

                {fieldError && (
                  <div className="flex items-start gap-2 rounded-xl bg-danger/10 border border-danger/20 px-3 py-2.5">
                    <AlertCircle className="w-4 h-4 text-danger shrink-0 mt-0.5" />
                    <p className="text-sm text-danger">{fieldError}</p>
                  </div>
                )}

                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={() => setStep('form')}
                    disabled={submitting}
                    className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-xl border border-border text-sm font-medium text-foreground hover:bg-accent transition-colors disabled:opacity-50"
                  >
                    <Pencil className="w-3.5 h-3.5" /> Edit
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirm}
                    disabled={submitting}
                    className="flex-1 btn-primary py-2.5 flex items-center justify-center gap-2"
                  >
                    {submitting && (
                      <div className="w-4 h-4 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
                    )}
                    {submitting ? 'Submitting…' : 'Confirm & Submit'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <p className="text-center text-xs text-subtle">
          Accounts are managed by your admin.{' '}
          <span className="font-semibold text-muted-foreground">No self-signup.</span>
        </p>
      </div>

      <SettingsHelpDrawer fieldKey={helpKey} onClose={() => setHelpKey(null)} />
    </div>
  );
}
