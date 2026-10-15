/**
 * The live notification list for the signed-in employee (ADR-516 D5).
 *
 * Before this, Home, the inbox and InterruptiveHost each fetched
 * `/notifications/{eid}` on their own and nothing refreshed them while the app
 * was open. The notification area needs one list that changes when something
 * arrives, so it lives here, mounted once in MainShell.
 *
 * It refreshes on: mount; app resume (AppState -> active); a foreground push
 * (the push is only a nudge, the server is the source); and every 60 s while
 * the app is active. Push alone is not enough: it is off where the platform
 * ARNs are empty, and iOS is parked.
 *
 * ARRIVALS are ids present in a refresh that were absent from the previous one.
 * The first load is never an arrival: opening the app is not "something just
 * happened", and bannering yesterday's backlog would teach people to ignore it.
 */
import React, {
  createContext, useCallback, useContext, useEffect, useMemo, useRef, useState,
} from 'react';
import { AppState } from 'react-native';
import apiClient from '@api/client';
import { onForegroundMessage } from '@api/pushRegistration';
import { useEmployeeId } from '@hooks/useEmployeeId';
import type { NotificationSeverity, NotificationTone } from '@components/notifications/tone';

export interface NotificationAction { label: string; route: string; style: string }

export interface LiveNotification {
  id: string;
  type: string;
  message: string;
  is_read: boolean;
  created_at: string;
  dispatch_date?: string | null;
  severity?: NotificationSeverity;
  label?: string;
  tone?: NotificationTone;
  icon?: string;
  channels?: string[];
  actions?: NotificationAction[];
}

interface NotificationsValue {
  /** Unread notifications, newest first. */
  unread: LiveNotification[];
  refresh: () => Promise<void>;
  markRead: (ids: string[]) => Promise<void>;
  /** Everything that arrived in the latest refresh, newest first. The area
   *  decides per tier what to do (banner, haptic, nothing); deciding here
   *  would lose an urgent arrival that landed beside a newer ticker event. */
  arrivals: LiveNotification[];
  clearArrivals: () => void;
}

const POLL_MS = 60_000;

const NotificationsCtx = createContext<NotificationsValue>({
  unread: [], refresh: async () => {}, markRead: async () => {},
  arrivals: [], clearArrivals: () => {},
});

export const useNotifications = () => useContext(NotificationsCtx);

export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const { fetchId } = useEmployeeId();
  const [unread, setUnread] = useState<LiveNotification[]>([]);
  const [arrivals, setArrivals] = useState<LiveNotification[]>([]);
  const known = useRef<Set<string> | null>(null);   // null until the first load
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlight.current) return;   // a resume and a push can land together
    inFlight.current = true;
    try {
      const eid = await fetchId();
      if (!eid) return;
      const res = await apiClient.get(`/notifications/${eid}?limit=50`);
      const rows: LiveNotification[] = (res.data ?? []).filter((n: LiveNotification) => !n.is_read);
      const ids = new Set(rows.map(n => n.id));
      if (known.current) {
        const fresh = rows.filter(n => !known.current!.has(n.id));
        if (fresh.length) setArrivals(fresh);   // server order: newest first
      }
      known.current = ids;
      setUnread(rows);
    } catch {
      // Silent: the area keeps what it had. A failed refresh must not put an
      // error over every screen; the inbox has its own error handling.
    } finally {
      inFlight.current = false;
    }
  }, [fetchId]);

  const markRead = useCallback(async (ids: string[]) => {
    if (!ids.length) return;
    setUnread(prev => prev.filter(n => !ids.includes(n.id)));   // optimistic
    await Promise.allSettled(ids.map(id => apiClient.patch(`/notifications/${id}/read`)));
    refresh();
  }, [refresh]);

  useEffect(() => {
    refresh();
    let timer: ReturnType<typeof setInterval> | null = setInterval(refresh, POLL_MS);
    const appSub = AppState.addEventListener('change', state => {
      if (state === 'active') {
        refresh();
        if (!timer) timer = setInterval(refresh, POLL_MS);
      } else if (timer) {
        clearInterval(timer);   // no polling from the background
        timer = null;
      }
    });
    const pushUnsub = onForegroundMessage(() => { refresh(); });
    return () => {
      if (timer) clearInterval(timer);
      appSub.remove();
      pushUnsub();
    };
  }, [refresh]);

  const value = useMemo(() => ({
    unread, refresh, markRead, arrivals, clearArrivals: () => setArrivals([]),
  }), [unread, refresh, markRead, arrivals]);

  return <NotificationsCtx.Provider value={value}>{children}</NotificationsCtx.Provider>;
}
