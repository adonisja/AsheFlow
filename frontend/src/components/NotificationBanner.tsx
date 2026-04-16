import React, { useEffect, useState } from 'react';
import { CheckCircle2, XCircle, AlertTriangle, Info, X, Bell } from 'lucide-react';
import axiosClient from '../api/axiosClient';

interface Notification {
  id: string;
  employee_id: string;
  type: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

interface Props {
  employeeId: string;
}

function styleForType(type: string): { bg: string; border: string; icon: React.ReactNode } {
  if (type.endsWith('_approved') || type.endsWith('_approved')) {
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
  // Default — informational
  return {
    bg: 'bg-info/10',
    border: 'border-info/30',
    icon: <Info className="w-4 h-4 text-info shrink-0 mt-0.5" />,
  };
}

const NotificationBanner: React.FC<Props> = ({ employeeId }) => {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  useEffect(() => {
    if (!employeeId) return;
    axiosClient
      .get<Notification[]>(`/notifications/${employeeId}`)
      .then((res) => setNotifications(res.data.filter((n) => !n.is_read)))
      .catch(console.error);
  }, [employeeId]);

  const dismiss = async (id: string) => {
    await axiosClient.patch(`/notifications/${id}/read`).catch(console.error);
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  };

  const dismissAll = async () => {
    await axiosClient.patch(`/notifications/employee/${employeeId}/read-all`).catch(console.error);
    setNotifications([]);
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
          <button onClick={dismissAll} className="text-xs text-muted-foreground hover:text-foreground underline transition-colors">
            Dismiss all
          </button>
        )}
      </div>
      {notifications.map((n) => {
        const style = styleForType(n.type);
        return (
          <div
            key={n.id}
            className={`flex items-start gap-3 px-4 py-3 rounded-xl border ${style.bg} ${style.border} shadow-sm`}
          >
            {style.icon}
            <p className="flex-1 text-sm font-medium text-foreground">{n.message}</p>
            <button onClick={() => dismiss(n.id)} className="text-muted-foreground hover:text-foreground transition-colors ml-2">
              <X className="w-4 h-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
};

export default NotificationBanner;
