import { errorText } from '../../utils/errorText';
import React, { useEffect, useState, useCallback } from 'react';
import { CheckCircle2, XCircle, Clock, Package, Loader2, RefreshCw, ChevronDown } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import axiosClient from '../../api/axiosClient';
import ErrorBanner from '../ui/ErrorBanner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GearItemResponse {
  id: string;
  item: string;
  size: string | null;
  season: string;
  status: 'pending' | 'approved' | 'denied' | 'fulfilled';
  approved_by: string | null;
  approved_at: string | null;
  fulfilled_by: string | null;
  fulfilled_at: string | null;
  notes: string | null;
  created_at: string;
}

interface GearOrderResponse {
  id: string;
  employee_id: string;
  employee_name: string;
  employee_role: string;
  submitted_at: string;
  items: GearItemResponse[];
}

type FilterTab = 'pending' | 'all';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ITEM_LABELS: Record<string, string> = {
  shirt_short: 'Short-Sleeved Shirt',
  shirt_long:  'Long-Sleeved Shirt',
  pants:       'Pants',
  shorts:      'Shorts',
  jacket:      'Jacket',
  vest:        'Vest',
  cap:         'Cap',
  gloves:      'Gloves',
};

const ITEM_IMAGES: Record<string, string> = {
  shirt_short: '/amazon_short_sleeved_shirt.webp',
  shirt_long:  '/amazon_long_sleeved_shirt.png',
  pants:       '/amazon_pants.jpeg',
  shorts:      '/amazon_shorts.jpeg',
  jacket:      '/amazon_jacket.jpeg',
  vest:        '/amazon_vest.webp',
  cap:         '/amazon_cap.webp',
  gloves:      '/gloves.webp',
};

const STATUS_CONFIG = {
  pending:   { label: 'Pending',   color: 'text-warning',  bg: 'bg-warning/10'  },
  approved:  { label: 'Approved',  color: 'text-info',     bg: 'bg-info/10'     },
  fulfilled: { label: 'Fulfilled', color: 'text-success',  bg: 'bg-success/10'  },
  denied:    { label: 'Denied',    color: 'text-danger',   bg: 'bg-danger/10'   },
};

function StatusBadge({ status }: { status: GearItemResponse['status'] }) {
  const cfg = STATUS_CONFIG[status];
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cfg.color} ${cfg.bg}`}>
      {cfg.label}
    </span>
  );
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', {
    weekday: 'short', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

function roleBadge(role: string) {
  return (
    <span className="text-xs text-muted-foreground capitalize bg-accent px-1.5 py-0.5 rounded">
      {role}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Item action row
// ---------------------------------------------------------------------------

interface ItemRowProps {
  item: GearItemResponse;
  onAction: (itemId: string, action: 'approve' | 'deny' | 'fulfill', notes?: string) => Promise<void>;
}

function ItemRow({ item, onAction }: ItemRowProps) {
  const [acting, setActing]         = useState(false);
  const [showDenyNotes, setShowDenyNotes] = useState(false);
  const [denyNotes, setDenyNotes]   = useState('');

  const act = async (action: 'approve' | 'deny' | 'fulfill', notes?: string) => {
    setActing(true);
    await onAction(item.id, action, notes);
    setActing(false);
    setShowDenyNotes(false);
    setDenyNotes('');
  };

  return (
    <div className="flex items-start gap-3 py-3">
      <img
        src={ITEM_IMAGES[item.item]}
        alt={ITEM_LABELS[item.item]}
        className="w-10 h-10 rounded-lg object-contain bg-accent p-1 shrink-0"
      />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm font-medium text-foreground">
            {ITEM_LABELS[item.item]}{item.size ? ` — ${item.size}` : ''}
          </p>
          <StatusBadge status={item.status} />
        </div>

        {item.notes && (
          <p className="text-xs text-muted-foreground mt-0.5 italic">{item.notes}</p>
        )}

        {/* Deny notes input */}
        <AnimatePresence>
          {showDenyNotes && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-2 space-y-2"
            >
              <input
                className="input-field text-xs"
                placeholder="Reason for denial (optional)"
                value={denyNotes}
                onChange={e => setDenyNotes(e.target.value)}
              />
              <div className="flex gap-2">
                <button
                  onClick={() => act('deny', denyNotes || undefined)}
                  disabled={acting}
                  className="text-xs font-medium text-danger hover:bg-danger/10 px-2 py-1 rounded-lg transition-colors"
                >
                  {acting ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Confirm Deny'}
                </button>
                <button
                  onClick={() => setShowDenyNotes(false)}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Action buttons */}
      {!acting && !showDenyNotes && (
        <div className="flex items-center gap-1.5 shrink-0">
          {item.status === 'pending' && (
            <>
              <button
                onClick={() => act('approve')}
                className="flex items-center gap-1 text-xs font-medium text-success hover:bg-success/10 px-2 py-1 rounded-lg transition-colors"
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                Approve
              </button>
              <button
                onClick={() => setShowDenyNotes(true)}
                className="flex items-center gap-1 text-xs font-medium text-danger hover:bg-danger/10 px-2 py-1 rounded-lg transition-colors"
              >
                <XCircle className="w-3.5 h-3.5" />
                Deny
              </button>
            </>
          )}
          {item.status === 'approved' && (
            <>
              <button
                onClick={() => act('fulfill')}
                className="flex items-center gap-1 text-xs font-medium text-primary hover:bg-primary/10 px-2 py-1 rounded-lg transition-colors"
              >
                <Package className="w-3.5 h-3.5" />
                Fulfill
              </button>
              <button
                onClick={() => setShowDenyNotes(true)}
                className="flex items-center gap-1 text-xs font-medium text-danger hover:bg-danger/10 px-2 py-1 rounded-lg transition-colors"
              >
                <XCircle className="w-3.5 h-3.5" />
                Deny
              </button>
            </>
          )}
        </div>
      )}

      {acting && <Loader2 className="w-4 h-4 animate-spin text-muted-foreground shrink-0" />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Order card
// ---------------------------------------------------------------------------

interface OrderCardProps {
  order: GearOrderResponse;
  onAction: (itemId: string, action: 'approve' | 'deny' | 'fulfill', notes?: string) => Promise<void>;
}

function OrderCard({ order, onAction }: OrderCardProps) {
  const pendingCount   = order.items.filter(i => i.status === 'pending').length;
  const approvedCount  = order.items.filter(i => i.status === 'approved').length;
  const fulfilledCount = order.items.filter(i => i.status === 'fulfilled').length;
  const deniedCount    = order.items.filter(i => i.status === 'denied').length;

  return (
    <div className="card space-y-1">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-foreground">{order.employee_name}</p>
            {roleBadge(order.employee_role)}
          </div>
          <p className="text-xs text-muted-foreground">{fmtDate(order.submitted_at)}</p>
        </div>
        {/* Summary chips */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {pendingCount > 0   && <span className="text-xs font-medium text-warning  bg-warning/10  px-2 py-0.5 rounded-full">{pendingCount} pending</span>}
          {approvedCount > 0  && <span className="text-xs font-medium text-info     bg-info/10     px-2 py-0.5 rounded-full">{approvedCount} approved</span>}
          {fulfilledCount > 0 && <span className="text-xs font-medium text-success  bg-success/10  px-2 py-0.5 rounded-full">{fulfilledCount} fulfilled</span>}
          {deniedCount > 0    && <span className="text-xs font-medium text-danger   bg-danger/10   px-2 py-0.5 rounded-full">{deniedCount} denied</span>}
        </div>
      </div>

      {/* Item rows */}
      <div className="divide-y divide-border">
        {order.items.map(item => (
          <ItemRow key={item.id} item={item} onAction={onAction} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function GearManagerInbox() {
  const [orders, setOrders]     = useState<GearOrderResponse[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [tab, setTab]           = useState<FilterTab>('pending');
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    else setRefreshing(true);
    setError(null);
    try {
      const endpoint = tab === 'pending' ? '/gear-requests/pending' : '/gear-requests/all';
      const res = await axiosClient.get<GearOrderResponse[]>(endpoint);
      setOrders(res.data);
    } catch {
      setError('Failed to load gear requests.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  const handleAction = async (itemId: string, action: 'approve' | 'deny' | 'fulfill', notes?: string) => {
    try {
      const res = await axiosClient.patch(`/gear-requests/items/${itemId}/${action}`, { notes: notes ?? null });
      const updatedItem: GearItemResponse = res.data;
      setOrders(prev => prev.map(order => ({
        ...order,
        items: order.items.map(i => i.id === itemId ? updatedItem : i),
      })));
      // Remove orders from pending view if no items remain pending
      if (tab === 'pending') {
        setOrders(prev => prev.filter(order =>
          order.items.some(i => i.status === 'pending')
        ));
      }
    } catch (err: any) {
      setError(errorText(err, 'Action failed.'));
    }
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-1 bg-accent rounded-xl p-1 text-sm">
          {(['pending', 'all'] as FilterTab[]).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 rounded-lg font-medium capitalize transition-colors ${
                tab === t
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {t === 'pending' ? 'Pending' : 'All Orders'}
            </button>
          ))}
        </div>
        <button
          onClick={() => load(true)}
          disabled={refreshing}
          className="btn-ghost flex items-center gap-1.5 text-sm"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {error && <ErrorBanner message={error} />}

      {loading ? (
        <div className="space-y-3">
          {[1, 2].map(i => <div key={i} className="card animate-pulse h-28" />)}
        </div>
      ) : orders.length === 0 ? (
        <div className="card flex flex-col items-center justify-center py-12 gap-3 text-center">
          <Package className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {tab === 'pending' ? 'No pending gear requests.' : 'No gear orders yet.'}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {orders.map(order => (
            <motion.div
              key={order.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
            >
              <OrderCard order={order} onAction={handleAction} />
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
