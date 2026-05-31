import React, { useEffect, useRef, useState } from 'react';
import { CheckCircle2, XCircle, AlertTriangle, Info, X, Bell } from 'lucide-react';
import axiosClient from '../api/axiosClient';

interface Notification {
  id: string;
  employee_id: string;
  type: string;
  message: string;
  is_read: boolean;
  created_at: string;
  dispatch_date: string | null;
}

interface Props {
  employeeId: string;
  onNotification?: (type: string) => void;
}

function styleForType(type: string): { bg: string; border: string; icon: React.ReactNode } {
  if (type === 'dispatch_assignment') {
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

// Tracks which dispatch_assignment notifications have been responded to in this session.
// Maps notification id → 'confirmed' | 'declined'
type ResponseMap = Record<string, 'confirmed' | 'declined'>;

const NotificationBanner: React.FC<Props> = ({ employeeId, onNotification }) => {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [responses, setResponses]         = useState<ResponseMap>({});
  const [responding, setResponding]       = useState<string | null>(null); // id currently being submitted
  const seenIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!employeeId) return;
    axiosClient
      .get<Notification[]>(`/notifications/${employeeId}`)
      .then((res) => {
        const unread = res.data.filter((n) => !n.is_read);
        setNotifications(unread);
        if (onNotification) {
          for (const n of unread) {
            if (!seenIds.current.has(n.id)) {
              seenIds.current.add(n.id);
              onNotification(n.type);
            }
          }
        }
      })
      .catch(() => {});
  }, [employeeId, onNotification]);

  const dismiss = async (id: string) => {
    await axiosClient.patch(`/notifications/${id}/read`).catch(() => {});
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  };

  const dismissAll = async () => {
    // Only dismiss non-dispatch notifications — dispatch_assignment cards require
    // an explicit Confirm or Decline response and cannot be bulk-dismissed.
    const nonDispatch = notifications.filter((n) => n.type !== 'dispatch_assignment');
    const responded   = notifications.filter((n) => n.type === 'dispatch_assignment' && responses[n.id]);
    const toRemove    = new Set([...nonDispatch, ...responded].map((n) => n.id));

    if (nonDispatch.length > 0) {
      await axiosClient.patch(`/notifications/employee/${employeeId}/read-all`).catch(() => {});
    }
    setNotifications((prev) => prev.filter((n) => !toRemove.has(n.id)));
  };

  const respondToDispatch = async (
    notif: Notification,
    status: 'confirmed' | 'declined',
  ) => {
    if (!notif.dispatch_date || responding) return;
    setResponding(notif.id);
    try {
      await axiosClient.post(`/dispatch/${notif.dispatch_date}/confirmations`, {
        employee_id: employeeId,
        status,
      });
      setResponses((prev) => ({ ...prev, [notif.id]: status }));
      // Mark the notification read after a short delay so the user sees their response
      setTimeout(() => dismiss(notif.id), 1800);
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
        {notifications.length > 1 && (
          <button
            onClick={dismissAll}
            className="text-xs text-muted-foreground hover:text-foreground underline transition-colors"
          >
            Dismiss all
          </button>
        )}
      </div>

      {notifications.map((n) => {
        const style = styleForType(n.type);

        if (n.type === 'dispatch_assignment') {
          const response = responses[n.id];
          const isSubmitting = responding === n.id;

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
                // Show recorded status — auto-dismissed after 1.8s
                <div className={`flex items-center gap-2 text-sm font-semibold ${
                  response === 'confirmed' ? 'text-success' : 'text-danger'
                }`}>
                  {response === 'confirmed'
                    ? <CheckCircle2 className="w-4 h-4" />
                    : <XCircle className="w-4 h-4" />
                  }
                  {response === 'confirmed' ? 'Confirmed' : 'Declined'} — response recorded.
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

        // Default render for all other notification types
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
