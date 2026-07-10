import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, XCircle, AlertTriangle, Info, X, Bell, MapPin } from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { useNotificationContext } from '../contexts/NotificationContext';
import type { Notification } from '../contexts/NotificationContext';

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

type ResponseMap = Record<string, 'confirmed' | 'declined'>;
type ConfirmationStatusMap = Record<string, 'pending' | 'confirmed' | 'declined' | null>;

const NotificationBanner: React.FC = () => {
  const { notifications, employeeId, markRead, markAllRead, refresh } = useNotificationContext();
  const [responses, setResponses] = useState<ResponseMap>({});
  const [responding, setResponding] = useState<string | null>(null);
  const [confirmationStatus, setConfirmationStatus] = useState<ConfirmationStatusMap>({});
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
    const requiresResponse = (n: Notification) =>
      n.type === 'dispatch_assignment' &&
      !responses[n.id] &&
      n.dispatch_date &&
      confirmationStatus[n.dispatch_date] === 'pending';

    const toRemove = notifications.filter(n => !requiresResponse(n));
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

  if (notifications.length === 0) return null;

  return (
    <div className="w-full space-y-2 animate-slide-up">
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

      {notifications.map(n => {
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
                <p className="flex-1 text-sm font-medium text-foreground">{n.message}</p>
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

        if (n.type === 'dispatch_assignment_info') {
          return (
            <div
              key={n.id}
              className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${style.bg} ${style.border} shadow-sm`}
            >
              {style.icon}
              <p className="flex-1 text-sm font-medium text-foreground">{n.message}</p>
              <button
                onClick={() => dismiss(n.id)}
                className="text-muted-foreground hover:text-foreground transition-colors ml-2"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          );
        }

        return (
          <div
            key={n.id}
            className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${style.bg} ${style.border} shadow-sm`}
          >
            {style.icon}
            <p className="flex-1 text-sm font-medium text-foreground">{n.message}</p>
            <button
              onClick={() => dismiss(n.id)}
              className="text-muted-foreground hover:text-foreground transition-colors ml-2"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
};

export default NotificationBanner;
