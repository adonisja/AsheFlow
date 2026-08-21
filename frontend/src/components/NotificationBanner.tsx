import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, XCircle, AlertTriangle, Info, X, Bell, MapPin, ChevronDown } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { useNotificationContext } from '../contexts/NotificationContext';
import type { Notification } from '../contexts/NotificationContext';
import { partitionNotifications } from './notifications/classify';

function styleForType(type: string): { bg: string; border: string; icon: React.ReactNode } {
  if (type === 'dispatch_assignment' || type === 'dispatch_assignment_info') {
    return {
      bg: 'bg-primary/10',
      border: 'border-primary/30',
      icon: <Bell className="w-4 h-4 text-primary shrink-0 mt-0.5" />,
    };
  }
  if (type.endsWith('_approved')) {
    return {
      bg: 'bg-success/10',
      border: 'border-success/30',
      icon: <CheckCircle2 className="w-4 h-4 text-success shrink-0 mt-0.5" />,
    };
  }
  if (type.endsWith('_rejected')) {
    return {
      bg: 'bg-danger/10',
      border: 'border-danger/30',
      icon: <XCircle className="w-4 h-4 text-danger shrink-0 mt-0.5" />,
    };
  }
  if (type === 'anchor_point_running_late') {
    return {
      bg: 'bg-warning/10',
      border: 'border-warning/30',
      icon: <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />,
    };
  }
  if (type.startsWith('anchor_point')) {
    return {
      bg: 'bg-info/10',
      border: 'border-info/30',
      icon: <MapPin className="w-4 h-4 text-info shrink-0 mt-0.5" />,
    };
  }
  if (type === 'timecard_adjustment' && import.meta.env.VITE_ADP_ENABLED === 'true') {
    return {
      bg: 'bg-warning/10',
      border: 'border-warning/30',
      icon: <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />,
    };
  }
  if (type.includes('critical') || type.includes('warning')) {
    return {
      bg: 'bg-warning/10',
      border: 'border-warning/30',
      icon: <AlertTriangle className="w-4 h-4 text-warning shrink-0 mt-0.5" />,
    };
  }
  return {
    bg: 'bg-info/10',
    border: 'border-info/30',
    icon: <Info className="w-4 h-4 text-info shrink-0 mt-0.5" />,
  };
}

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
    const toRemove = info;
    if (toRemove.some(n => n.type !== 'dispatch_assignment')) {
      await markAllRead();
    } else {
      await Promise.all(toRemove.map(n => markRead(n.id)));
    }
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

  if (notifications.length === 0) return null;

  return (
    /* HEIGHT CAP (ADR-275 D3) — a safety net, not the mechanism. D1 bounds the
       informational side; the action side is deliberately uncapped because
       hiding an unanswered assignment can strand a truck. This guarantees page
       content stays visible even on a genuine multi-truck day. If this cap is
       ever doing real work, the classification is wrong. */
    <div className="w-full space-y-2 animate-slide-up max-h-[40vh] overflow-y-auto pr-1">
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
          {notifications.length > 1 && (
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
        const style = styleForType(n.type);

        if (n.type === 'dispatch_assignment') {
          const response = responses[n.id];
          const isSubmitting = responding === n.id;
          const backendStatus = n.dispatch_date ? confirmationStatus[n.dispatch_date] : undefined;
          const windowOpen = backendStatus === undefined || backendStatus === 'pending';

          return (
            <div
              key={n.id}
              className={`flex flex-col gap-3 px-4 py-3 rounded-xl border ${style.bg} ${style.border} shadow-sm`}
            >
              <div className="flex items-start gap-3">
                {style.icon}
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
                  {response === 'confirmed' ? 'Confirmed' : 'Declined'} — response recorded.
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

      {/* INFORMATIONAL GROUP (ADR-275 D2). One row when there is more than one;
          a lone update renders as a normal card, because collapsing a single
          item hides it behind a click for no saving. */}
      {info.length === 1 && <InfoCard n={info[0]} onDismiss={dismiss} />}

      {info.length > 1 && (
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
              {info.length} more update{info.length === 1 ? '' : 's'}
            </span>
            {/* A preview of the most recent, so the row says something even
                closed — "12 more updates" alone gives no reason to open it. */}
            <span className="hidden sm:block max-w-[45%] truncate text-xs text-muted-foreground">
              {stripMarkdown(info[0].message)}
            </span>
          </button>

          {/* Inset and separated, so the expanded items read as CONTENTS of the
              group rather than siblings that escaped it. Without the divider
              and the left inset the cards looked like they had broken out of
              the container they belong to. */}
          {infoOpen && (
            <div className="border-t border-border/60 bg-background/40 px-2 py-2 space-y-1.5">
              {info.map(n => (
                <InfoCard key={n.id} n={n} onDismiss={dismiss} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

/** One informational row. Extracted because the collapsed group and the
 *  single-item case render the same thing — two copies would drift. */
const InfoCard: React.FC<{ n: Notification; onDismiss: (id: string) => void }> = ({
  n,
  onDismiss,
}) => {
  const style = styleForType(n.type);
  return (
    <div
      className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${style.bg} ${style.border} shadow-sm`}
    >
      {style.icon}
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
