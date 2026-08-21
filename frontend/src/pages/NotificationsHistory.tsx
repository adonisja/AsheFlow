import React, { useEffect, useState, useCallback } from 'react';
import {
  Bell, CheckCircle2, XCircle, AlertTriangle, Info, MapPin,
  RefreshCw, Trash2, Check,
} from 'lucide-react';
import axiosClient from '../api/axiosClient';
import { useNotificationContext } from '../contexts/NotificationContext';
import type { Notification } from '../contexts/NotificationContext';

interface HistoryNotification extends Notification {
  expires_at: string | null;
}

function iconForType(type: string) {
  if (type.endsWith('_approved'))           return <CheckCircle2 className="w-4 h-4 text-success shrink-0" />;
  if (type.endsWith('_rejected'))           return <XCircle className="w-4 h-4 text-danger shrink-0" />;
  if (type === 'anchor_point_running_late') return <AlertTriangle className="w-4 h-4 text-warning shrink-0" />;
  if (type.startsWith('anchor_point'))      return <MapPin className="w-4 h-4 text-info shrink-0" />;
  if (type === 'timecard_adjustment')       return <AlertTriangle className="w-4 h-4 text-warning shrink-0" />;
  if (type === 'dispatch_assignment')       return <Bell className="w-4 h-4 text-primary shrink-0" />;
  if (type.includes('critical') || type.includes('warning')) return <AlertTriangle className="w-4 h-4 text-warning shrink-0" />;
  return <Info className="w-4 h-4 text-info shrink-0" />;
}

function labelForType(type: string): string {
  return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  if (diffMins < 1)  return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

type Filter = 'all' | 'unread' | 'read';

export default function NotificationsHistory() {
  const { employeeId, markRead, markAllRead } = useNotificationContext();
  const [all, setAll] = useState<HistoryNotification[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<Filter>('all');
  const [page, setPage] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const PAGE_SIZE = 50;

  const load = useCallback(async (reset = false) => {
    if (!employeeId) return;
    setLoading(true);
    const skip = reset ? 0 : page * PAGE_SIZE;
    try {
      const res = await axiosClient.get<HistoryNotification[]>(`/notifications/${employeeId}`, {
        params: { skip, limit: PAGE_SIZE },
      });
      const rows = res.data;
      setHasMore(rows.length === PAGE_SIZE);
      setAll(prev => reset ? rows : [...prev, ...rows]);
      if (!reset) setPage(p => p + 1);
    } finally {
      setLoading(false);
    }
  }, [employeeId, page]);

  useEffect(() => {
    if (employeeId) {
      setPage(0);
      load(true);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employeeId]);

  const handleMarkRead = async (id: string) => {
    await markRead(id);
    setAll(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n));
  };

  const handleMarkAllRead = async () => {
    await markAllRead();
    setAll(prev => prev.map(n => ({ ...n, is_read: true })));
  };

  const visible = all.filter(n => {
    if (filter === 'unread') return !n.is_read;
    if (filter === 'read')   return n.is_read;
    return true;
  });

  const unreadCount = all.filter(n => !n.is_read).length;

  return (
    <div className="space-y-6 animate-slide-up">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="page-title flex items-center gap-2">
            <Bell className="w-5 h-5 text-primary" />
            Notifications
          </h1>
          {unreadCount > 0 && (
            <p className="text-subtle mt-0.5">{unreadCount} unread</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { setPage(0); load(true); }}
            disabled={loading}
            className="btn-ghost text-xs flex items-center gap-1.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          {unreadCount > 0 && (
            <button
              onClick={handleMarkAllRead}
              className="btn-ghost text-xs flex items-center gap-1.5"
            >
              <Check className="w-3.5 h-3.5" />
              Mark all read
            </button>
          )}
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-1 bg-accent rounded-xl p-1 w-fit text-sm">
        {(['all', 'unread', 'read'] as Filter[]).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg font-medium capitalize transition-colors ${
              filter === f
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* List */}
      {visible.length === 0 && !loading ? (
        <div className="card text-center py-12">
          <Bell className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
          <p className="text-muted-foreground text-sm">
            {filter === 'unread' ? "You're all caught up." : 'No notifications yet.'}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {visible.map(n => (
            <div
              key={n.id}
              className={`flex items-start gap-3 px-4 py-3 rounded-xl border transition-colors ${
                n.is_read
                  ? 'bg-card border-border/40 opacity-70'
                  : 'bg-card border-border shadow-sm'
              }`}
            >
              <div className="mt-0.5">{iconForType(n.type)}</div>
              <div className="flex-1 min-w-0">
                <p className={`text-sm ${n.is_read ? 'text-muted-foreground' : 'text-foreground font-medium'}`}>
                  {n.message}
                </p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-muted-foreground">{labelForType(n.type)}</span>
                  <span className="text-muted-foreground/40 text-xs">·</span>
                  <span className="text-xs text-muted-foreground">{fmtTime(n.created_at)}</span>
                </div>
              </div>
              {!n.is_read && (
                <button
                  onClick={() => handleMarkRead(n.id)}
                  className="shrink-0 text-muted-foreground hover:text-foreground transition-colors mt-0.5"
                  title="Mark as read"
                >
                  <Check className="w-4 h-4" />
                </button>
              )}
              {n.is_read && (
                <CheckCircle2 className="w-4 h-4 text-muted-foreground/30 shrink-0 mt-0.5" />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Load more */}
      {hasMore && filter === 'all' && (
        <div className="flex justify-center">
          <button
            onClick={() => load(false)}
            disabled={loading}
            className="btn-ghost text-xs flex items-center gap-1.5"
          >
            {loading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5 hidden" />}
            {loading ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  );
}
