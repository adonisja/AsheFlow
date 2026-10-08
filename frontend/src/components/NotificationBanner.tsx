import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, XCircle, X, Bell, ChevronDown } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { useNotificationContext } from '../contexts/NotificationContext';
import type { Notification } from '../contexts/NotificationContext';
import { partitionNotifications } from './notifications/classify';
import { NotificationTicker } from './notifications/NotificationTicker';
import { TONE_CARD, TONE_TEXT, URGENT_CARD, isTicker, isUrgent } from './notifications/tone';

/**
 * Where an URGENT notification's action link goes (ADR-487 D4a).
 *
 * URGENT has no X. It is dismissable only by ACTING, because a
 * dismissed-but-unhandled injury alert is the warningless wall ADR-381
 * described — so the card carries the link that resolves it instead.
 *
 * Every destination below is a route that EXISTS in App.tsx, checked rather
 * than assumed: a link to an invented path is the ADR-381 failure in its purest
 * form (the feature ships, the type is exported, nothing is reachable).
 *
 * The default is /notifications rather than a guess. A new URGENT type with no
 * entry here still gets a working link to the archive, where the message is
 * readable in full — degraded, but never broken.
 */
const URGENT_ROUTES: Record<string, { to: string; label: string }> = {
  incident_critical: { to: '/incidents', label: 'View incident' },
  driver_help_requested: { to: '/crew-status', label: 'View crew status' },
  trainee_help_request: { to: '/crew-status', label: 'View crew status' },
  rebalance_intervention_required: { to: '/dispatch', label: 'Open dispatch' },
};

function urgentDestination(type: string): string {
  return URGENT_ROUTES[type]?.to ?? '/notifications';
}

function urgentActionLabel(type: string): string {
  return URGENT_ROUTES[type]?.label ?? 'View details';
}

/**
 * The assignment card's own palette (ADR-487 D4).
 *
 * `dispatch_assignment` is the ONLY type in the action group — isActionRequired
 * returns false for everything else — and it is deliberately `primary` rather
 * than a registry tone: it is the one notification that asks the reader a
 * question, and "awaiting your answer" is a different axis from "good / warn /
 * bad". A tone would make it look like news.
 *
 * This replaces `styleForType`, a chain of string-prefix guesses:
 *
 *     if (type.includes('critical') || type.includes('warning')) -> warning
 *     if (type.endsWith('_rejected'))                            -> danger
 *     if (type.startsWith('anchor_point'))                       -> info
 *
 * which put `incident_critical` (URGENT) in the same bucket as a timecard
 * notice, gave any new type whatever the chain happened to match, and existed
 * in differently-worded copies on the history page, the navbar dropdown and
 * mobile. Every other card now takes its colours from the server's `tone`.
 *
 * One branch of that chain is NOT carried over, deliberately:
 *
 *     if (type === 'timecard_adjustment' && VITE_ADP_ENABLED === 'true')
 *
 * It was dead twice. `VITE_ADP_ENABLED` is `false` in .env, .env.template and
 * .env.production, so the branch never fired in any environment — and
 * `timecard_adjustment` is not a notification type at all. Every occurrence of
 * that string in the backend is a table name or an audit action_type; the real
 * types are the six `timecard_*` entries in SPEC. The clients were styling a
 * type nothing raises.
 */
const ASSIGNMENT_CARD = 'bg-primary/10 border-primary/30';

/** Notification messages carry Discord-flavoured markdown (**bold**) because the
 *  same string is posted to a channel. Rendered as plain text the asterisks leak
 *  through — "**Falcon**" was visible on screen. */
function stripMarkdown(text: string): string {
  return text.replace(/\*\*(.*?)\*\*/g, '$1').replace(/\*(.*?)\*/g, '$1');
}

/** RENDER the bold rather than strip it. The bolded span is always the thing
 *  that matters — the truck name, the date — so flattening it throws away the
 *  one bit of emphasis the message author encoded. Split on the delimiters and
 *  emit <strong>; no markdown library for one rule.
 *
 *  Used for full message text. The collapsed preview still STRIPS, because a
 *  one-line truncated summary should not carry weight changes. */
function renderMessage(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4 ? (
      <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
    ) : (
      <React.Fragment key={i}>{part}</React.Fragment>
    ),
  );
}

type ResponseMap = Record<string, 'confirmed' | 'declined'>;
type ConfirmationStatusMap = Record<string, 'pending' | 'confirmed' | 'declined' | null>;

const NotificationBanner: React.FC = () => {
  const { notifications, employeeId, markRead, markAllRead, refresh } = useNotificationContext();
  const [responses, setResponses] = useState<ResponseMap>({});
  const [responding, setResponding] = useState<string | null>(null);
  const [confirmationStatus, setConfirmationStatus] = useState<ConfirmationStatusMap>({});
  const [infoOpen, setInfoOpen] = useState(false);
  const fetchedDates = useRef<Set<string>>(new Set());

  // Fetch confirmation window status for any new dispatch_assignment notifications
  useEffect(() => {
    const dates = [
      ...new Set(
        notifications
          .filter(n => n.type === 'dispatch_assignment' && n.dispatch_date)
          .map(n => n.dispatch_date as string)
          .filter(d => !fetchedDates.current.has(d)),
      ),
    ];
    if (dates.length === 0) return;

    dates.forEach(d => fetchedDates.current.add(d));

    Promise.allSettled(
      dates.map(d =>
        axiosClient
          .get<{ date: string; status: 'pending' | 'confirmed' | 'declined' | null }>(
            `/dispatch/${d}/my-confirmation`,
          )
          .then(r => ({ date: d, status: r.data.status })),
      ),
    ).then(results => {
      const statusMap: ConfirmationStatusMap = {};
      for (const r of results) {
        if (r.status === 'fulfilled') statusMap[r.value.date] = r.value.status;
      }
      setConfirmationStatus(prev => ({ ...prev, ...statusMap }));
    });
  }, [notifications]);

  const dismiss = (id: string) => markRead(id);

  const dismissAll = async () => {
    // Never bulk-dismiss something awaiting an answer (ADR-275 D1). Uses the
    // SAME classifier as the render split — this used to be a second, subtly
    // different copy of the rule inline.
    //
    // ADR-487 D4a adds URGENT to that exclusion, and it cannot ride on
    // markAllRead: that endpoint only spares actionable dispatch_assignments,
    // so a bulk call would clear an injury alert server-side. ADR-275's own
    // note — "dismissing an unanswered assignment is not the same as clearing
    // an announcement" — applies here with more force, so this dismisses row
    // by row and leaves URGENT standing.
    const toRemove = [...ticker, ...news];
    await Promise.all(toRemove.map(n => markRead(n.id)));
  };

  /** Clear the ticker strip only, leaving cards and URGENT alone. */
  const dismissTicker = async () => {
    await Promise.all(ticker.map(n => markRead(n.id)));
  };

  const respondToDispatch = async (notif: Notification, status: 'confirmed' | 'declined') => {
    if (!notif.dispatch_date || responding) return;
    setResponding(notif.id);
    try {
      await axiosClient.post(`/dispatch/${notif.dispatch_date}/confirmations`, {
        employee_id: employeeId,
        status,
      });
      setResponses(prev => ({ ...prev, [notif.id]: status }));
      setTimeout(() => {
        dismiss(notif.id);
        refresh();
      }, 1800);
    } catch (e) {
      console.error('Failed to record confirmation:', e);
    } finally {
      setResponding(null);
    }
  };

  // ADR-275 D1 — what needs an answer vs what is only news.
  const { action, info } = partitionNotifications(notifications, {
    answeredInSession: responses,
    confirmationStatus,
  });

  /* ADR-487 D4 — the informational half now splits again, by where the server
     says each type routes. Three groups out of `info`:

       urgent  — its own region, ABOVE the height cap (D4a)
       ticker  — events with no consequence for the reader (D4b)
       news    — INFO about the reader: stays a card, as today

     Severity is NOT the ticker test. 52 types are INFO and only 20 carry
     'ticker'; `pto_approved` is INFO and must not scroll past, because it is a
     decision about the reader's own time off. The server sends `channels` for
     exactly this reason — see tone.ts.

     URGENT is drawn from `info` rather than `action` because `action` means
     "awaiting YOUR answer" (a dispatch_assignment confirm/decline). An injury
     alert needs no answer from the reader; it needs to be impossible to miss,
     which is a different property with a different mechanism. */
  const urgent = info.filter(n => isUrgent(n.severity));
  const rest = info.filter(n => !isUrgent(n.severity));
  const ticker = rest.filter(n => isTicker(n.channels));
  const news = rest.filter(n => !isTicker(n.channels));

  if (notifications.length === 0) return null;

  return (
    /* ADR-487 D4a — the banner is now an UNCAPPED outer wrapper holding (1) the
       URGENT region and (2) the capped, scrollable container that was
       previously this whole component.

       This is a structural change, not a class move, and the ADR says so
       plainly: the 40vh cap works by SCROLLING its contents, so anything inside
       it can be scrolled past and left unseen. Acceptable for an announcement;
       not for an injury. "Render it above" sounds like a one-line reorder and
       is not — the URGENT region has to live outside the element that scrolls. */
    <div className="w-full space-y-2 animate-slide-up">
      {/* URGENT — outside the cap, so it cannot be scrolled away. Not a live
          region: it is a card the reader is meant to ACT on, not an
          announcement to interrupt them with. */}
      {urgent.length > 0 && (
        <div className="space-y-2">
          {urgent.map(n => (
            <div
              key={n.id}
              className={`rounded-xl border p-3 ${URGENT_CARD}`}
            >
              <div className="flex items-start gap-3">
                <span aria-hidden="true" className="text-lg leading-none shrink-0 mt-0.5">
                  {n.icon}
                </span>
                <div className="min-w-0 flex-1">
                  <div className={`text-sm font-semibold ${TONE_TEXT[n.tone] ?? TONE_TEXT.bad}`}>
                    {n.label}
                  </div>
                  <div className="mt-0.5 text-sm text-foreground">
                    {renderMessage(n.message)}
                  </div>
                  {/* Dismissable only by ACTING. No X: a dismissed-but-unhandled
                      injury alert is the warningless wall ADR-381 described. The
                      link resolves the alert by taking the reader to the thing
                      it is about. */}
                  <Link
                    to={urgentDestination(n.type)}
                    className="mt-2 inline-flex items-center gap-1 text-xs font-medium
                               text-danger hover:underline"
                  >
                    {urgentActionLabel(n.type)}
                  </Link>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* HEIGHT CAP (ADR-275 D3) — a safety net, not the mechanism. D1 bounds the
          informational side; the action side is deliberately uncapped because
          hiding an unanswered assignment can strand a truck. This guarantees page
          content stays visible even on a genuine multi-truck day. If this cap is
          ever doing real work, the classification is wrong. */}
      <div className="w-full space-y-2 max-h-[40vh] overflow-y-auto pr-1">
        <div className="flex items-center justify-between mb-1">
          <span className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            <Bell className="w-3.5 h-3.5" />
            Notifications
          </span>
          <span className="flex items-center gap-3">
            {/* Dismissing only clears the banner — full history stays at /notifications */}
            <Link
              to="/notifications"
              className="text-xs text-muted-foreground hover:text-foreground underline transition-colors"
            >
              View all
            </Link>
            {/* Only when there is something bulk-dismissable. URGENT is excluded
                from the bulk action, so a lone injury alert must not render a
                button that would appear to do nothing. */}
            {ticker.length + news.length > 1 && (
              <button
                onClick={dismissAll}
                className="text-xs text-muted-foreground hover:text-foreground underline transition-colors"
              >
                Dismiss all
              </button>
            )}
          </span>
        </div>

        {action.map(n => {
          if (n.type === 'dispatch_assignment') {
            const response = responses[n.id];
            const isSubmitting = responding === n.id;
            const backendStatus = n.dispatch_date ? confirmationStatus[n.dispatch_date] : undefined;
            const windowOpen = backendStatus === undefined || backendStatus === 'pending';

            return (
              <div
                key={n.id}
                className={`flex flex-col gap-3 px-4 py-3 rounded-xl border ${ASSIGNMENT_CARD} shadow-sm`}
              >
                <div className="flex items-start gap-3">
                  <Bell className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                  <p className="flex-1 text-sm text-foreground">{renderMessage(n.message)}</p>
                </div>

                {response ? (
                  <div className={`flex items-center gap-2 text-sm font-semibold ${
                    response === 'confirmed' ? 'text-success' : 'text-danger'
                  }`}>
                    {response === 'confirmed'
                      ? <CheckCircle2 className="w-4 h-4" />
                      : <XCircle className="w-4 h-4" />
                    }
                    {response === 'confirmed' ? 'Confirmed' : 'Declined'}. Response recorded.
                  </div>
                ) : !windowOpen ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    {backendStatus === 'confirmed' && (
                      <>
                        <CheckCircle2 className="w-4 h-4 text-success" />
                        <span>You confirmed this assignment.</span>
                      </>
                    )}
                    {backendStatus === 'declined' && (
                      <>
                        <XCircle className="w-4 h-4 text-danger" />
                        <span>You declined this assignment.</span>
                      </>
                    )}
                    {backendStatus === null && (
                      <span>The confirmation window for this assignment has closed.</span>
                    )}
                    <button
                      onClick={() => dismiss(n.id)}
                      className="ml-auto text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <button
                      disabled={isSubmitting}
                      onClick={() => respondToDispatch(n, 'confirmed')}
                      className="btn-primary text-xs px-4 py-1.5 flex items-center gap-1.5"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      {isSubmitting ? 'Saving…' : 'Confirm ✓'}
                    </button>
                    <button
                      disabled={isSubmitting}
                      onClick={() => respondToDispatch(n, 'declined')}
                      className="btn-danger text-xs px-4 py-1.5 flex items-center gap-1.5"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      {isSubmitting ? 'Saving…' : 'Decline ✗'}
                    </button>
                  </div>
                )}
              </div>
            );
          }

          // UNREACHABLE BY CONSTRUCTION. `action` only ever contains
          // dispatch_assignment (isActionRequired returns false for every other
          // type, verified), so the old dispatch_assignment_info and generic
          // branches that lived here were dead once the partition landed. Every
          // other type now renders through InfoCard below.
          return null;
        })}

        {/* INFO ABOUT THE READER (ADR-275 D2, narrowed by ADR-487 D4b). The 52
            INFO types split 20 ticker / 32 banner, and these are the 32 whose
            subject is the reader — pto_approved, rts_rejected, role_change — so
            they stay cards and stay in the scroll region. A decision about your
            own time off must not scroll past.

            (ADR-487 D4b says "31" and "18 of 80"; both predate the final review
            pass. Counted from SPEC, which is the authority.)

            One row when there is more than one; a lone update renders as a normal
            card, because collapsing a single item hides it behind a click for no
            saving. */}
        {news.length === 1 && <InfoCard n={news[0]} onDismiss={dismiss} />}

        {news.length > 1 && (
          <div className="rounded-xl border border-border bg-accent/20 overflow-hidden">
            <button
              onClick={() => setInfoOpen(o => !o)}
              aria-expanded={infoOpen}
              className="w-full flex items-center gap-2 px-4 py-2.5 text-left
                         hover:bg-accent/30 transition-colors"
            >
              <ChevronDown
                className={`w-4 h-4 text-muted-foreground shrink-0 transition-transform
                            ${infoOpen ? '' : '-rotate-90'}`}
              />
              <span className="flex-1 text-sm font-medium text-foreground">
                {news.length} more update{news.length === 1 ? '' : 's'}
              </span>
              {/* A preview of the most recent, so the row says something even
                  closed — "12 more updates" alone gives no reason to open it. */}
              <span className="hidden sm:block max-w-[45%] truncate text-xs text-muted-foreground">
                {stripMarkdown(news[0].message)}
              </span>
            </button>

            {/* Inset and separated, so the expanded items read as CONTENTS of the
                group rather than siblings that escaped it. Without the divider
                and the left inset the cards looked like they had broken out of
                the container they belong to. */}
            {infoOpen && (
              <div className="border-t border-border/60 bg-background/40 px-2 py-2 space-y-1.5">
                {news.map(n => (
                  <InfoCard key={n.id} n={n} onDismiss={dismiss} />
                ))}
              </div>
            )}
          </div>
        )}

        {/* EVENTS THAT HAPPENED (ADR-487 D4b). Last inside the cap: it is the
            lowest-consequence group, so it is the one that may scroll out of
            view. Dismissal clears the whole strip at once — these are
            acknowledgements, not decisions, and an X per item would be more
            chrome than content on a 28px row. */}
        <NotificationTicker items={ticker} onDismissAll={dismissTicker} />
      </div>
    </div>
  );
};

/** One informational row. Extracted because the collapsed group and the
 *  single-item case render the same thing — two copies would drift.
 *
 *  Styled from the server's `tone` (ADR-487 D4), not from guessing at the type
 *  string. The old `styleForType` chain put `incident_critical` and
 *  `timecard_adjustment` in the same bucket because both matched
 *  `type.includes('critical')` / `'warning'` — the exact gap ADR-487 opens
 *  with. It also meant this card and the ticker could disagree about the same
 *  notification, since only one of them consulted the registry. */
const InfoCard: React.FC<{ n: Notification; onDismiss: (id: string) => void }> = ({
  n,
  onDismiss,
}) => {
  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${TONE_CARD[n.tone] ?? TONE_CARD.neutral} shadow-sm`}
    >
      <span aria-hidden="true" className={`shrink-0 mt-0.5 ${TONE_TEXT[n.tone] ?? TONE_TEXT.neutral}`}>
        {n.icon}
      </span>
      <p className="flex-1 text-sm text-foreground">{renderMessage(n.message)}</p>
      <button
        onClick={() => onDismiss(n.id)}
        className="text-muted-foreground hover:text-foreground transition-colors ml-2"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
};

export default NotificationBanner;
