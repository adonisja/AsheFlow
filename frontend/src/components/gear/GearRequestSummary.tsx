/**
 * Dashboard summary of the gear approval queue.
 *
 * Deliberately NOT the full inbox (GearManagerInbox) — that lives on /gear.
 * A dashboard widget answers "does this need me?" at a glance and links onward;
 * duplicating the interactive queue in two places means two implementations of
 * the same actions drifting apart.
 *
 * So: counts, the oldest waiting request, what is being asked for, and a link.
 * No approve/deny/fulfil here — those are the page's job.
 *
 * There is no summary endpoint, so this reads /gear-requests/pending (already
 * management-gated) and aggregates client-side.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ShoppingBag, ArrowRight, Clock, CheckCircle2 } from 'lucide-react';
import axiosClient from '../../api/axiosClient';
import { count, age } from '../../utils/metric';

interface GearItem {
  id: string;
  item: string;
  status: 'pending' | 'approved' | 'denied' | 'fulfilled';
}

interface GearOrder {
  id: string;
  employee_name: string;
  employee_role: string;
  submitted_at: string;
  items: GearItem[];
}

/** Requests older than this are called out as waiting too long. */
const STALE_HOURS = 48;

export default function GearRequestSummary() {
  const [orders, setOrders] = useState<GearOrder[] | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await axiosClient.get<GearOrder[]>('/gear-requests/pending');
      setOrders(res.data);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const header = (
    <div className="flex items-center gap-2 border-b border-border pb-3 mb-4">
      <ShoppingBag className="w-5 h-5 text-primary" />
      <h2 className="text-base font-semibold text-foreground">Gear Requests</h2>
      <Link
        to="/gear"
        className="ml-auto text-xs text-primary hover:underline flex items-center gap-1"
      >
        Review all <ArrowRight className="w-3 h-3" />
      </Link>
    </div>
  );

  if (failed) {
    return (
      <div className="card">
        {header}
        <p className="text-sm text-subtle text-center py-4">Unavailable.</p>
      </div>
    );
  }

  if (orders === null) {
    return (
      <div className="card">
        {header}
        <div className="animate-pulse h-16 rounded-lg bg-accent/30" />
      </div>
    );
  }

  const pendingItems = orders.reduce(
    (n, o) => n + o.items.filter(i => i.status === 'pending').length, 0,
  );

  // Oldest first — a queue is judged by its worst wait, not its average.
  const submitted = orders
    .map(o => new Date(o.submitted_at).getTime())
    .filter(t => !Number.isNaN(t));
  const oldestMinutes = submitted.length
    ? Math.round((Date.now() - Math.min(...submitted)) / 60000)
    : null;
  const stale = (oldestMinutes ?? 0) > STALE_HOURS * 60;

  // Which items are actually being asked for — tells a manager whether this is
  // routine uniform replacement or something unusual, without opening the page.
  const byItem = new Map<string, number>();
  for (const o of orders) {
    for (const i of o.items) {
      if (i.status === 'pending') byItem.set(i.item, (byItem.get(i.item) ?? 0) + 1);
    }
  }
  const topItems = [...byItem.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3);

  if (orders.length === 0) {
    return (
      <div className="card">
        {header}
        <p className="text-sm text-subtle text-center py-4 flex items-center justify-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-success" />
          No requests awaiting review.
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      {header}

      <div className="grid grid-cols-3 gap-2 sm:gap-3">
        <div className="p-2 sm:p-3 rounded-lg bg-accent/20">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Orders</p>
          <p className="text-xl font-bold text-foreground mt-0.5 tabular-nums">
            {count(orders.length)}
          </p>
        </div>
        <div className="p-2 sm:p-3 rounded-lg bg-accent/20">
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Items</p>
          <p className="text-xl font-bold text-foreground mt-0.5 tabular-nums">
            {count(pendingItems)}
          </p>
        </div>
        <div className={`p-2 sm:p-3 rounded-lg ${stale ? 'bg-warning/10 border border-warning/20' : 'bg-accent/20'}`}>
          <p className="text-xs text-muted-foreground uppercase tracking-wider">Oldest</p>
          <p className={`text-xl font-bold mt-0.5 tabular-nums ${stale ? 'text-warning' : 'text-foreground'}`}>
            {age(oldestMinutes)}
          </p>
        </div>
      </div>

      {stale && (
        <p className="mt-3 text-xs text-warning flex items-center gap-1">
          <Clock className="w-3 h-3" />
          Waiting over {STALE_HOURS}h
        </p>
      )}

      {topItems.length > 0 && (
        <div className="mt-4 space-y-1.5">
          <p className="text-xs text-subtle uppercase tracking-wider">Most requested</p>
          {topItems.map(([item, n]) => (
            <div key={item} className="flex items-center justify-between gap-2">
              <span className="text-sm text-foreground truncate capitalize">
                {item.replace(/_/g, ' ')}
              </span>
              <span className="text-sm font-semibold text-foreground shrink-0 tabular-nums">
                {count(n)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
