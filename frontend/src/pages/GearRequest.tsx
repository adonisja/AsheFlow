import { errorText } from '../utils/errorText';
import React, { useEffect, useState } from 'react';
import { ShoppingCart, CheckCircle2, XCircle, Clock, Loader2, AlertTriangle, Trash2, HelpCircle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import axiosClient from '../api/axiosClient';
import SectionHeader from '../components/ui/SectionHeader';
import ErrorBanner from '../components/ui/ErrorBanner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CatalogueItem {
  item: string;
  season: 'summer' | 'winter' | 'all';
  available: boolean;
  sizes: string[];
  no_size: boolean;
}

interface CatalogueResponse {
  current_season: 'summer' | 'winter';
  items: CatalogueItem[];
}

interface GearItemResponse {
  id: string;
  item: string;
  size: string | null;
  season: string;
  status: 'pending' | 'approved' | 'denied' | 'fulfilled';
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
  pending:   { label: 'Pending',   color: 'text-warning',  bg: 'bg-warning/10',  icon: Clock },
  approved:  { label: 'Approved',  color: 'text-info',     bg: 'bg-info/10',     icon: CheckCircle2 },
  fulfilled: { label: 'Fulfilled', color: 'text-success',  bg: 'bg-success/10',  icon: CheckCircle2 },
  denied:    { label: 'Denied',    color: 'text-danger',   bg: 'bg-danger/10',   icon: XCircle },
};

function StatusBadge({ status }: { status: GearItemResponse['status'] }) {
  const cfg = STATUS_CONFIG[status];
  const Icon = cfg.icon;
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${cfg.color} ${cfg.bg}`}>
      <Icon className="w-3 h-3" />
      {cfg.label}
    </span>
  );
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// ---------------------------------------------------------------------------
// Cart item row
// ---------------------------------------------------------------------------

interface CartEntry {
  item: string;
  size: string;
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function GearRequest() {
  const [catalogue, setCatalogue] = useState<CatalogueResponse | null>(null);
  const [orders, setOrders]       = useState<GearOrderResponse[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);

  // Cart state
  const [cart, setCart]           = useState<CartEntry[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | string[] | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [catRes, ordersRes] = await Promise.all([
        axiosClient.get<CatalogueResponse>('/gear-requests/catalogue'),
        axiosClient.get<GearOrderResponse[]>('/gear-requests/my-orders'),
      ]);
      setCatalogue(catRes.data);
      setOrders(ordersRes.data);
    } catch {
      setError('Failed to load gear catalogue.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const cartItemKeys = new Set(cart.map(c => c.item));

  const addToCart = (item: CatalogueItem) => {
    if (cartItemKeys.has(item.item)) return;
    setCart(prev => [...prev, { item: item.item, size: item.sizes[0] ?? '' }]);
    setSubmitError(null);
    setSubmitSuccess(false);
  };

  const removeFromCart = (item: string) => {
    setCart(prev => prev.filter(c => c.item !== item));
  };

  const updateSize = (item: string, size: string) => {
    setCart(prev => prev.map(c => c.item === item ? { ...c, size } : c));
  };

  const handleSubmit = async () => {
    if (cart.length === 0) return;
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(false);
    try {
      await axiosClient.post('/gear-requests/', {
        items: cart.map(c => ({ item: c.item, size: c.size || null })),
      });
      setCart([]);
      setSubmitSuccess(true);
      const ordersRes = await axiosClient.get<GearOrderResponse[]>('/gear-requests/my-orders');
      setOrders(ordersRes.data);
      setTimeout(() => setSubmitSuccess(false), 4000);
    } catch (err: any) {
      const detail = errorText(err, '') || undefined;
      setSubmitError(Array.isArray(detail) ? detail : (detail ?? 'Failed to submit order.'));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-60 items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !catalogue) {
    return <ErrorBanner message={error ?? 'Failed to load catalogue.'} />;
  }

  const summerItems    = catalogue.items.filter(i => i.season === 'summer');
  const winterItems    = catalogue.items.filter(i => i.season === 'winter');
  const allSeasonItems = catalogue.items.filter(i => i.season === 'all');
  const currentSeason  = catalogue.current_season;

  const unavailableLabel = (season: CatalogueItem['season']) => {
    if (season === 'summer') return 'Summer season only';
    if (season === 'winter') return 'Winter season only';
    return '';
  };

  const renderGrid = (items: CatalogueItem[]) => (
    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-4">
      {items.map(catItem => {
        const inCart    = cartItemKeys.has(catItem.item);
        const available = catItem.available;
        return (
          <div
            key={catItem.item}
            className={`card flex flex-col items-center gap-3 p-4 transition-all ${
              !available ? 'opacity-40 select-none' : inCart ? 'ring-2 ring-primary' : 'hover:ring-1 hover:ring-primary/40 cursor-pointer'
            }`}
            onClick={() => available && !inCart && addToCart(catItem)}
          >
            <div className="w-full aspect-square rounded-lg overflow-hidden bg-accent flex items-center justify-center">
              <img
                src={ITEM_IMAGES[catItem.item]}
                alt={ITEM_LABELS[catItem.item]}
                className="object-contain w-full h-full"
              />
            </div>
            <p className="text-xs font-medium text-center text-foreground">{ITEM_LABELS[catItem.item]}</p>

            {!available && (
              <span className="text-xs text-muted-foreground flex items-center gap-1">
                <AlertTriangle className="w-3 h-3" />
                {unavailableLabel(catItem.season)}
              </span>
            )}
            {available && inCart && (
              <span className="text-xs text-primary font-medium flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3" />
                In cart
              </span>
            )}
            {available && !inCart && (
              <span className="text-xs text-muted-foreground">Tap to add</span>
            )}
          </div>
        );
      })}
    </div>
  );

  return (
    <div className="space-y-8 animate-slide-up">
      <SectionHeader
        title="Gear Request"
        description={`Request work gear. Currently ${currentSeason === 'summer' ? 'Summer' : 'Winter'} season — ${currentSeason === 'summer' ? 'winter' : 'summer'} items are unavailable.`}
      />

      {/* ---- Season grid ---- */}
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Summer Gear</h2>
        {renderGrid(summerItems)}
      </div>
      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-foreground">Winter Gear</h2>
        {renderGrid(winterItems)}
      </div>
      {allSeasonItems.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-foreground">All-Season Gear</h2>
          {renderGrid(allSeasonItems)}
        </div>
      )}

      {/* ---- Cart ---- */}
      <AnimatePresence>
        {cart.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            className="card space-y-4"
          >
            <div className="flex items-center gap-2">
              <ShoppingCart className="w-4 h-4 text-primary" />
              <h3 className="font-semibold text-sm">Your Order ({cart.length} item{cart.length > 1 ? 's' : ''})</h3>
            </div>

            <div className="divide-y divide-border">
              {cart.map(entry => {
                const catItem = catalogue.items.find(c => c.item === entry.item)!;
                return (
                  <div key={entry.item} className="flex items-center gap-3 py-3">
                    <img
                      src={ITEM_IMAGES[entry.item]}
                      alt={ITEM_LABELS[entry.item]}
                      className="w-10 h-10 rounded-lg object-contain bg-accent p-1"
                    />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-foreground">{ITEM_LABELS[entry.item]}</p>
                      {catItem.no_size ? (
                        <p className="text-xs text-muted-foreground">One size</p>
                      ) : (
                        <select
                          className="mt-1 text-xs bg-accent border border-border rounded-lg px-2 py-1 text-foreground"
                          value={entry.size}
                          onChange={e => updateSize(entry.item, e.target.value)}
                        >
                          {catItem.sizes.map(s => (
                            <option key={s} value={s}>{s}</option>
                          ))}
                        </select>
                      )}
                    </div>
                    <button
                      onClick={() => removeFromCart(entry.item)}
                      className="text-muted-foreground hover:text-danger transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                );
              })}
            </div>

            {submitError && (
              <div className="rounded-lg bg-danger/8 border border-danger/20 p-3 space-y-1">
                {Array.isArray(submitError) ? (
                  submitError.map((e, i) => (
                    <p key={i} className="text-xs text-danger">{e}</p>
                  ))
                ) : (
                  <p className="text-xs text-danger">{submitError}</p>
                )}
              </div>
            )}

            <div className="flex items-center justify-between">
              <button
                onClick={() => setCart([])}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                Clear cart
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="btn-primary flex items-center gap-2 text-sm"
              >
                {submitting ? (
                  <><Loader2 className="w-4 h-4 animate-spin" />Submitting…</>
                ) : (
                  <><ShoppingCart className="w-4 h-4" />Submit Order</>
                )}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {submitSuccess && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-2 rounded-xl bg-success/10 border border-success/20 px-4 py-3 text-sm text-success"
        >
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          Order submitted successfully. Your manager will review it shortly.
        </motion.div>
      )}

      {/* ---- Order history ---- */}
      {orders.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-foreground">Your Order History</h2>
          <div className="space-y-3">
            {orders.map(order => (
              <div key={order.id} className="card space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-xs text-muted-foreground">{fmtDate(order.submitted_at)}</p>
                  <p className="text-xs text-muted-foreground">{order.items.length} item{order.items.length > 1 ? 's' : ''}</p>
                </div>
                <div className="space-y-2">
                  {order.items.map(item => (
                    <div key={item.id} className="flex items-center gap-3">
                      <img
                        src={ITEM_IMAGES[item.item]}
                        alt={ITEM_LABELS[item.item]}
                        className="w-8 h-8 rounded object-contain bg-accent p-0.5"
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-foreground">
                          {ITEM_LABELS[item.item]}{item.size ? ` — ${item.size}` : ''}
                        </p>
                        {item.notes && item.status === 'denied' && (
                          <p className="text-xs text-muted-foreground truncate">{item.notes}</p>
                        )}
                      </div>
                      <StatusBadge status={item.status} />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
