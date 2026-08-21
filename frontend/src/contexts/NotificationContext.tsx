import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { fetchAuthSession } from 'aws-amplify/auth';
import axiosClient from '../api/axiosClient';
import { useAuth } from './AuthContext';

export interface Notification {
  id: string;
  employee_id: string;
  type: string;
  message: string;
  is_read: boolean;
  created_at: string;
  dispatch_date: string | null;
  expires_at: string | null;
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
