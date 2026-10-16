import React, { useEffect, useMemo, useState } from 'react';
import { Bell, MessageSquare, Search, Send, Smartphone, SquareStack, TriangleAlert } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import SelectMenu, { type SelectOption } from '../../components/ui/SelectMenu';
import NotificationBanner from '../../components/NotificationBanner';
import InterruptiveHost from '../../components/notifications/InterruptiveHost';
import { PreviewNotificationProvider } from '../../contexts/NotificationContext';
import type { Notification, NotificationAction } from '../../contexts/NotificationContext';

/** Every notification type, on every surface it reaches, before anyone receives
 *  it (ADR-507).
 *
 *  The previews are the PRODUCTION components inside PreviewNotificationProvider:
 *  NotificationBanner draws the banner/urgent/ticker region exactly as a user
 *  sees it, and InterruptiveHost picks the same pop-up it would pick live. Push
 *  and Discord have no in-app component, so those two are mock-ups built from
 *  the rules the backend uses (push title = registry label, body = message).
 *
 *  "Send" raises a REAL notification of the type to a test employee, through
 *  every channel, so the phone shows the real thing (ADR-507 D3). The server
 *  refuses any employee in a live company.
 */

type CopySource = 'template' | 'indirect' | 'unraised';

interface GalleryType {
  type: string;
  label: string;
  severity: Notification['severity'];
  tone: Notification['tone'];
  icon: string;
  channels: string[];
  actions: NotificationAction[];
  copy_source: CopySource;
  templates: { location: string; text: string }[];
  sample_text: string;
  preview_message: string;
}

interface Target {
  company_id: string;
  company_name: string;
  data_class: string;
  employees: { id: string; name: string; username: string | null; role: string }[];
}

const CHANNELS = ['banner', 'ticker', 'push', 'discord', 'prompt', 'gate'] as const;

const SOURCE_COPY: Record<CopySource, { label: string; hint: string; className: string }> = {
  template: {
    label: 'Real copy',
    hint: 'Read from the code that raises it.',
    className: 'bg-success/10 text-success',
  },
  indirect: {
    label: 'Sourced sample',
    hint: 'Raised through a computed type, so the text was copied from the code that builds it.',
    className: 'bg-info/10 text-info',
  },
  unraised: {
    label: 'Never raised',
    hint: 'Declared in the registry, raised by nothing, so no real text exists. The text shown is a placeholder written for this preview.',
    className: 'bg-warning/10 text-warning',
  },
};

/** A notification object for one preview. Action routes point back at this
 *  page (its current path), so following a pop-up's button closes the preview instead of taking a
 *  super admin into a tenant screen. The label the user would see is unchanged. */
function toPreview(t: GalleryType, channels?: string[]): Notification {
  return {
    id: `preview-${t.type}`,
    employee_id: 'preview',
    type: t.type,
    message: t.preview_message,
    is_read: false,
    created_at: new Date().toISOString(),
    dispatch_date: null,
    expires_at: null,
    severity: t.severity,
    label: t.label,
    tone: t.tone,
    icon: t.icon,
    channels: channels ?? t.channels,
    // The page's own path, read at preview time rather than hardcoded, so the
    // no-op holds wherever the gallery is mounted.
    actions: t.actions.map(a => ({ ...a, route: window.location.pathname })),
  } as Notification;
}

/** Template text with its ‹placeholders› shown as chips, so what is interpolated
 *  (including any personal name) is visible at a glance. */
function TemplateText({ text }: { text: string }) {
  const parts = text.split(/(‹[^›]*›)/g);
  return (
    <span>
      {parts.map((p, i) =>
        p.startsWith('‹') ? (
          <code key={i} className="mx-0.5 rounded bg-surface-muted px-1 py-0.5 font-mono text-[0.8em] text-muted-foreground">
            {p.slice(1, -1)}
          </code>
        ) : (
          <React.Fragment key={i}>{p}</React.Fragment>
        ),
      )}
    </span>
  );
}

function PushMock({ t }: { t: GalleryType }) {
  return (
    <div className="max-w-sm rounded-2xl border border-border bg-surface-muted p-3">
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-primary text-[0.6rem] font-bold text-primary-foreground">A</span>
        <span>AsheFlow</span>
        <span aria-hidden="true">·</span>
        <span>now</span>
      </div>
      <p className="mt-1.5 text-sm font-semibold text-foreground">{t.label}</p>
      <p className="mt-0.5 line-clamp-3 text-sm text-foreground">{t.preview_message}</p>
    </div>
  );
}

function DiscordMock({ t }: { t: GalleryType }) {
  return (
    <div className="max-w-md rounded-lg border border-border bg-surface-muted p-3">
      <p className="text-xs font-semibold text-foreground">AsheFlow Bot</p>
      <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">{t.preview_message}</p>
    </div>
  );
}

function SurfaceLabel({ icon: Icon, children }: { icon: typeof Bell; children: React.ReactNode }) {
  return (
    <p className="mb-1.5 flex items-center gap-1.5 text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {children}
    </p>
  );
}

function TypeRow({
  t,
  canSend,
  onSend,
  sending,
}: {
  t: GalleryType;
  canSend: boolean;
  onSend: (type: string) => void;
  sending: boolean;
}) {
  const [popup, setPopup] = useState<{ key: number; channels: string[] } | null>(null);
  const interruptive = t.channels.includes('gate') || t.channels.includes('prompt');
  const inApp = t.channels.some(c => c === 'banner' || c === 'ticker');
  const preview = useMemo(() => [toPreview(t)], [t]);
  const src = SOURCE_COPY[t.copy_source];

  return (
    <article id={t.type} className="rounded-2xl border border-border bg-card p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">
            <span aria-hidden="true" className="mr-1.5">{t.icon}</span>
            {t.label}
          </h2>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">{t.type}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="rounded-full border border-border px-2 py-0.5 text-xs font-medium text-foreground">{t.severity}</span>
          {t.channels.map(c => (
            <span key={c} className="rounded-full bg-surface-muted px-2 py-0.5 text-xs text-muted-foreground">{c}</span>
          ))}
          <span title={src.hint} className={`rounded-full px-2 py-0.5 text-xs font-medium ${src.className}`}>{src.label}</span>
        </div>
      </header>

      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <section aria-label="Copy">
          <SurfaceLabel icon={SquareStack}>Copy</SurfaceLabel>
          {t.templates.length > 0 ? (
            <ul className="space-y-2">
              {/* Keyed by position too: one raise site can build several messages
                  (one per if/else branch), so `location` alone repeats. */}
              {t.templates.map((tpl, i) => (
                <li key={`${tpl.location}#${i}`} className="rounded-lg bg-surface-muted p-3 text-sm text-foreground">
                  <TemplateText text={tpl.text} />
                  <p className="mt-1.5 font-mono text-[0.7rem] text-muted-foreground">{tpl.location}</p>
                </li>
              ))}
            </ul>
          ) : (
            <div className="rounded-lg bg-surface-muted p-3 text-sm text-foreground">
              <TemplateText text={t.sample_text} />
              <p className="mt-1.5 text-[0.75rem] text-muted-foreground">{src.hint}</p>
            </div>
          )}
          {t.actions.length > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              Action: <span className="font-medium text-foreground">{t.actions[0].label}</span>
            </p>
          )}
        </section>

        <section aria-label="Previews" className="space-y-4">
          {inApp && (
            <div>
              <SurfaceLabel icon={Bell}>In the app</SurfaceLabel>
              {/* inert: a preview is for looking. The banner's own buttons call
                  the API (assignment confirmations), and a super admin must not
                  fire them by accident. */}
              <div inert className="rounded-xl border border-dashed border-border p-2">
                <PreviewNotificationProvider notifications={preview}>
                  <NotificationBanner />
                </PreviewNotificationProvider>
              </div>
            </div>
          )}

          {interruptive && (
            <div>
              <SurfaceLabel icon={TriangleAlert}>Pop-up</SurfaceLabel>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setPopup({ key: Date.now(), channels: t.channels })}
                  className="min-h-9 rounded-lg border border-border-strong px-3 text-sm font-medium text-foreground hover:bg-surface-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t.channels.includes('gate') ? 'Open as gate' : 'Open pop-up'}
                </button>
                {t.channels.includes('gate') && (
                  <button
                    type="button"
                    onClick={() => setPopup({
                      key: Date.now(),
                      channels: [...t.channels.filter(c => c !== 'gate'), 'prompt'],
                    })}
                    className="min-h-9 rounded-lg border border-border-strong px-3 text-sm font-medium text-foreground hover:bg-surface-muted focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    Open as prompt (before its deadline)
                  </button>
                )}
              </div>
              {popup && (
                <PreviewNotificationProvider key={popup.key} notifications={[toPreview(t, popup.channels)]}>
                  <InterruptiveHost />
                </PreviewNotificationProvider>
              )}
            </div>
          )}

          {t.channels.includes('push') && (
            <div>
              <SurfaceLabel icon={Smartphone}>Push (mock-up)</SurfaceLabel>
              <PushMock t={t} />
            </div>
          )}

          {t.channels.includes('discord') && (
            <div>
              <SurfaceLabel icon={MessageSquare}>Discord (mock-up)</SurfaceLabel>
              <DiscordMock t={t} />
            </div>
          )}

          {!inApp && !interruptive && !t.channels.includes('push') && !t.channels.includes('discord') && (
            <p className="text-sm text-muted-foreground">Inbox only. It appears in the notification list and nowhere else.</p>
          )}
        </section>
      </div>

      <footer className="mt-4 flex justify-end">
        <button
          type="button"
          disabled={!canSend || sending}
          onClick={() => onSend(t.type)}
          className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-semibold text-primary-foreground hover:bg-primary/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-50"
        >
          <Send className="h-4 w-4" aria-hidden="true" />
          {sending ? 'Sending' : 'Send'}
        </button>
      </footer>
    </article>
  );
}

export default function NotificationGallery() {
  const [types, setTypes] = useState<GalleryType[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [query, setQuery] = useState('');
  const [channel, setChannel] = useState<string | null>(null);
  const [targets, setTargets] = useState<Target[]>([]);
  const [recipient, setRecipient] = useState('');
  const [sending, setSending] = useState<string | null>(null);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    axiosClient.get<{ types: GalleryType[] }>('/platform/notification-gallery')
      .then(r => setTypes(r.data.types))
      .catch(() => setLoadError(true));
    axiosClient.get<{ companies: Target[] }>('/platform/notification-gallery/targets')
      .then(r => setTargets(r.data.companies))
      .catch(() => setTargets([]));
  }, []);

  const visible = useMemo(() => {
    if (!types) return [];
    const q = query.trim().toLowerCase();
    return types.filter(t =>
      (!channel || t.channels.includes(channel)) &&
      (!q || t.type.includes(q) || t.label.toLowerCase().includes(q) || t.sample_text.toLowerCase().includes(q)),
    );
  }, [types, query, channel]);

  const counts = useMemo(() => {
    const c = { template: 0, indirect: 0, unraised: 0 } as Record<CopySource, number>;
    types?.forEach(t => { c[t.copy_source] += 1; });
    return c;
  }, [types]);

  const recipientOptions = useMemo<SelectOption[]>(() => targets.flatMap(co => [
    { value: `header-${co.company_id}`, label: `${co.company_name} (${co.data_class})`, header: true },
    ...co.employees.map(e => ({ value: e.id, label: e.username ?? e.name, hint: e.role })),
  ]), [targets]);

  const recipientLabel = useMemo(() => {
    for (const co of targets) {
      const e = co.employees.find(x => x.id === recipient);
      if (e) return e.username ?? e.name;
    }
    return '';
  }, [targets, recipient]);

  const send = async (type: string) => {
    setSending(type);
    setStatus(null);
    try {
      await axiosClient.post(`/platform/notification-gallery/${type}/send`, { employee_id: recipient });
      setStatus({ ok: true, text: `Sent ${type} to ${recipientLabel}. Open their app to see it.` });
    } catch {
      setStatus({ ok: false, text: `Could not send ${type}. Check the recipient is in a test or demo company.` });
    } finally {
      setSending(null);
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-foreground">Notifications</h1>
        {types && (
          <p className="mt-1 text-sm text-muted-foreground">
            {types.length} types: {counts.template} with real copy, {counts.indirect} with a sourced sample,{' '}
            <span className="font-medium text-warning">{counts.unraised} never raised</span>.
          </p>
        )}
      </header>

      <div className="sticky top-0 z-10 space-y-3 rounded-2xl border border-border bg-background/95 p-4 backdrop-blur">
        <div className="flex flex-wrap items-center gap-3">
          <label className="relative min-w-[16rem] flex-1">
            <span className="sr-only">Search notifications</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search by name, type or text"
              className="min-h-10 w-full rounded-lg border border-border bg-surface pl-9 pr-3 text-sm text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
          <div className="flex items-center gap-2 text-sm text-foreground">
            <span id="send-to-label">Send to</span>
            {/* The house dropdown (SelectMenu), not a native <select>: grouped
                under a heading per company, with each person's role as the hint.
                The owner flagged the native one as off-pattern. */}
            <div className="min-w-[16rem]">
              <SelectMenu
                value={recipient}
                options={recipientOptions}
                placeholder={targets.length === 0 ? 'No test companies here' : 'Choose a test employee'}
                onChange={setRecipient}
                ariaLabel="Send to"
              />
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by channel">
          {[null, ...CHANNELS].map(c => (
            <button
              key={c ?? 'all'}
              type="button"
              aria-pressed={channel === c}
              onClick={() => setChannel(c)}
              className={`min-h-8 rounded-full px-3 text-xs font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-ring ${
                channel === c ? 'bg-primary text-primary-foreground' : 'bg-surface-muted text-foreground hover:bg-accent'
              }`}
            >
              {c ?? 'All'}
            </button>
          ))}
        </div>
        {status && (
          <p role="status" className={`text-sm ${status.ok ? 'text-success' : 'text-danger'}`}>{status.text}</p>
        )}
      </div>

      {loadError && (
        <p className="rounded-lg bg-danger/10 p-4 text-sm text-danger">Could not load the notification catalogue. Reload to try again.</p>
      )}
      {!types && !loadError && <p className="text-sm text-muted-foreground">Loading the catalogue…</p>}

      <div className="space-y-4">
        {visible.map(t => (
          <TypeRow key={t.type} t={t} canSend={!!recipient} onSend={send} sending={sending === t.type} />
        ))}
        {types && visible.length === 0 && (
          <p className="text-sm text-muted-foreground">No notification matches that search.</p>
        )}
      </div>
    </div>
  );
}
