import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { fetchAuthSession } from 'aws-amplify/auth';
import axiosClient from '../api/axiosClient';
import { useAuth } from './AuthContext';

/** How urgently this notification needs to be seen (ADR-487 D1). */
export type NotificationSeverity = 'urgent' | 'action' | 'notice' | 'info';

/** What the message MEANS, not what colour to paint it (ADR-487 D4).
 *
 *  The server deliberately sends no colour: this surface owns Tailwind classes
 *  and mobile owns a React Native theme object, and the two are not
 *  interchangeable. A hex value from a Python file would land in one of the two
 *  themes unreadable. Each surface maps tone -> its own token.
 */
export type NotificationTone = 'neutral' | 'good' | 'warn' | 'bad' | 'active';

export interface Notification {
  id: string;
  employee_id: string;
  type: string;
  message: string;
  is_read: boolean;
  created_at: string;
  dispatch_date: string | null;
  expires_at: string | null;

  /** Resolved from the server's registry per read, not stored on the row.
   *  Present on BOTH transports — the REST list and the SSE stream — because
   *  the two serialise separately on the server and a client that trusted one
   *  but not the other would render a severity-less card for live arrivals. */
  severity: NotificationSeverity;
  label: string;
  tone: NotificationTone;
  icon: string;

  /** Which channels this type routes to, e.g. ['banner'] or ['ticker'].
   *
   *  Sent rather than derived, because "does this scroll in the ticker" is not
   *  a function of severity: 52 types are INFO and only 20 carry 'ticker'. The
   *  rule is about the message's SUBJECT — INFO about the reader goes to the
   *  banner, INFO about a third party or the system goes to the ticker — which
   *  this surface cannot compute. Hardcoding the 20 would drift from the
   *  server the first time a type is added. */
  channels: string[];
}

interface NotificationContextType {
  notifications: Notification[];
  unreadCount: number;
  employeeId: string | null;
  markRead: (id: string) => Promise<void>;
  markAllRead: () => Promise<void>;
  refresh: () => void;
  setOnNotification: (cb: ((type: string) => void) | null) => void;
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined);

const ELIGIBLE_GROUPS = ['driver', 'walker', 'trainer', 'trainee', 'dispatch'];
const BASE_URL = import.meta.env.VITE_API_URL as string;

export const NotificationProvider = ({ children }: { children: React.ReactNode }) => {
  const { isAuthenticated, groups } = useAuth();
  const [employeeId, setEmployeeId] = useState<string | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const onNotificationRef = useRef<((type: string) => void) | null>(null);
  const seenIds = useRef<Set<string>>(new Set());
  const esRef = useRef<EventSource | null>(null);

  const setOnNotification = useCallback((cb: ((type: string) => void) | null) => {
    onNotificationRef.current = cb;
  }, []);

  const isEligible = isAuthenticated && groups.some(g => ELIGIBLE_GROUPS.includes(g));

  const _applyIncoming = useCallback((incoming: Notification[]) => {
    const fresh = incoming.filter(n => !seenIds.current.has(n.id));
    if (fresh.length === 0) return;

    fresh.forEach(n => seenIds.current.add(n.id));
    setNotifications(prev => {
      const existingIds = new Set(prev.map(n => n.id));
      const added = fresh.filter(n => !existingIds.has(n.id));
      return added.length > 0 ? [...added, ...prev] : prev;
    });

    const cb = onNotificationRef.current;
    if (cb) fresh.forEach(n => cb(n.type));
  }, []);

  const refresh = useCallback(() => {
    if (!employeeId) return;
    axiosClient
      .get<Notification[]>(`/notifications/${employeeId}`, { params: { limit: 50 } })
      .then(res => {
        const unread = res.data.filter(n => !n.is_read);
        // Reset seen tracking to allow re-delivery of anything still unread
        seenIds.current = new Set();
        setNotifications(unread);
        unread.forEach(n => seenIds.current.add(n.id));
      })
      .catch(() => {});
  }, [employeeId]);

  // Open SSE stream once employeeId is known
  useEffect(() => {
    if (!employeeId) return;

    let active = true;

    const openStream = async () => {
      try {
        const session = await fetchAuthSession();
        const token = session.tokens?.idToken?.toString();
        if (!token || !active) return;

        const url = `${BASE_URL}/notifications/${employeeId}/stream?token=${encodeURIComponent(token)}`;
        const es = new EventSource(url);
        esRef.current = es;

        es.onmessage = (evt) => {
          try {
            const incoming: Notification[] = JSON.parse(evt.data);
            _applyIncoming(incoming);
          } catch {
            // malformed event — ignore
          }
        };

        es.onerror = () => {
          // EventSource will auto-reconnect; close and reopen to refresh the token
          es.close();
          esRef.current = null;
          if (active) setTimeout(openStream, 5_000);
        };
      } catch {
        if (active) setTimeout(openStream, 10_000);
      }
    };

    openStream();

    return () => {
      active = false;
      esRef.current?.close();
      esRef.current = null;
    };
  }, [employeeId, _applyIncoming]);

  // Resolve employeeId on mount
  useEffect(() => {
    if (!isEligible) return;

    axiosClient.get<{ id: string }>('/employees/me')
      .then(res => setEmployeeId(res.data.id))
      .catch(() => {});
  }, [isEligible]);

  const markRead = useCallback(async (id: string) => {
    await axiosClient.patch(`/notifications/${id}/read`).catch(() => {});
    setNotifications(prev => prev.filter(n => n.id !== id));
  }, []);

  const markAllRead = useCallback(async () => {
    if (!employeeId) return;
    await axiosClient.patch(`/notifications/employee/${employeeId}/read-all`).catch(() => {});
    setNotifications([]);
  }, [employeeId]);

  return (
    <NotificationContext.Provider value={{
      notifications,
      unreadCount: notifications.length,
      employeeId,
      markRead,
      markAllRead,
      refresh,
      setOnNotification,
    }}>
      {children}
    </NotificationContext.Provider>
  );
};

export const useNotificationContext = () => {
  const ctx = useContext(NotificationContext);
  if (!ctx) throw new Error('useNotificationContext must be used within NotificationProvider');
  return ctx;
};
