import { useEffect, useMemo, useRef, useState } from 'react';
import { Package, Search, Check, X } from 'lucide-react';
import type { SeedBag } from '../../utils/walkerLogSeed';
import { swatchFor } from './bagColors';

/** Bag picker for a route's totes.
 *
 *  A native <select> was the first cut and it failed on this data: 59 options
 *  in one flat list, no search, no grouping, and on a laptop the popup ran off
 *  the bottom of the screen. Finding "Green 7522" meant scrolling a wall of
 *  near-identical strings — and the labels ARE near-identical: six colors and a
 *  number, so the eye has almost nothing to lock onto.
 *
 *  What this does instead, in the order it matters:
 *    1. TYPE TO FILTER. Matches bag, stop (WE93) or sort zone (A-16.3E) — the
 *       three things actually printed on the label and the shelf.
 *    2. THE COLOR IS A SWATCH. "Navy", "Green", "Orange" are physical bag
 *       colors, so showing the color makes a run of options scannable in a way
 *       the word never is.
 *    3. GROUPED BY STOP, because bags travel together. WE93's three bags being
 *       adjacent under a heading is how a walker thinks about the load.
 *    4. Keyboard: up/down move, Enter picks, Escape closes — a picker used 59
 *       times a morning must not require the mouse.
 *
 *  It stays a popup rather than becoming a modal: the route it belongs to has
 *  to stay visible, since choosing a bag is judged against what the route
 *  already holds.
 */

export default function TotePicker({ pool, onPick, disabled }: {
  /** Unclaimed bags only. Anything in here is safe to assign. */
  pool: SeedBag[];
  onPick: (b: SeedBag) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return pool;
    // Every term must match somewhere, so "green we94" narrows rather than
    // widening the way a single-substring test would.
    const terms = q.split(/\s+/);
    return pool.filter((b) => {
      const hay = `${b.bag_id} ${b.stop} ${b.sort_zone}`.toLowerCase();
      return terms.every((t) => hay.includes(t));
    });
  }, [pool, query]);

  /** Runs of bags sharing a stop, in pool order — which is manifest order, so
   *  the list reads WE91 to WE114 the way the sheet does. */
  const groups = useMemo(() => {
    const out: { stop: string; bags: SeedBag[] }[] = [];
    for (const b of matches) {
      const last = out[out.length - 1];
      if (last && last.stop === b.stop) last.bags.push(b);
      else out.push({ stop: b.stop, bags: [b] });
    }
    return out;
  }, [matches]);

  // Cursor indexes `matches`, so it has to come back in range whenever the
  // filter shrinks the list - otherwise Enter picks nothing, or the wrong bag.
  useEffect(() => { setCursor(0); }, [query]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
    else setQuery('');
  }, [open]);

  // Keep the highlighted row on screen during keyboard navigation.
  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector('[data-active="true"]')
      ?.scrollIntoView({ block: 'nearest' });
  }, [cursor, open]);

  const pick = (b: SeedBag) => {
    onPick(b);
    // Stay open: totes are added in runs, and reopening for each of a stop's
    // four bags is four extra clicks. The pool shrinks under the cursor, so the
    // bag just taken disappears on its own.
    setQuery('');
    setCursor(0);
    inputRef.current?.focus();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, matches.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); if (matches[cursor]) pick(matches[cursor]); }
    else if (e.key === 'Escape') { e.preventDefault(); setOpen(false); }
  };

  const empty = pool.length === 0;

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        disabled={disabled || empty}
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="btn-secondary text-xs px-2.5 py-1 inline-flex items-center gap-1.5 disabled:opacity-40 focus:outline-none focus:ring-2 focus:ring-primary/40"
      >
        <Package className="w-3.5 h-3.5" />
        {empty ? 'No totes left' : `Add tote (${pool.length})`}
      </button>

      {open && (
        <div className="absolute right-0 z-40 mt-1.5 w-[22rem] max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card shadow-lg overflow-hidden">
          <div className="relative border-b border-border">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKey}
              placeholder="Bag, stop (WE93) or zone (A-16.3E)"
              className="w-full bg-transparent pl-9 pr-9 py-2.5 text-sm outline-none"
            />
            {query && (
              <button
                type="button" onClick={() => { setQuery(''); inputRef.current?.focus(); }}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 p-0.5 rounded text-muted-foreground hover:text-foreground"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <div ref={listRef} className="max-h-72 overflow-y-auto py-1" role="listbox">
            {matches.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                No unassigned tote matches that.
              </p>
            ) : groups.map((g) => {
              const b0 = g.bags[0];
              const partial = g.bags.length < b0.stop_bag_count;
              return (
                <div key={g.stop}>
                  <div className="flex items-baseline justify-between gap-2 px-3 pt-2 pb-1">
                    <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {g.stop}
                      {partial && <span className="ml-1 text-warning normal-case tracking-normal">
                        · {g.bags.length} of {b0.stop_bag_count} left
                      </span>}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {b0.stop_package_count} pkg · {b0.stop_ov_count} OV
                    </span>
                  </div>
                  {g.bags.map((b) => {
                    const idx = matches.indexOf(b);
                    return (
                      <button
                        key={b.bag_id}
                        type="button"
                        role="option"
                        aria-selected={idx === cursor}
                        data-active={idx === cursor}
                        onMouseEnter={() => setCursor(idx)}
                        onClick={() => pick(b)}
                        className={`w-full flex items-center gap-2.5 px-3 py-1.5 text-left text-sm ${
                          idx === cursor ? 'bg-accent/60' : ''
                        }`}
                      >
                        <span
                          aria-hidden
                          className="w-2.5 h-2.5 rounded-full ring-1 ring-black/10 shrink-0"
                          style={{ background: swatchFor(b.bag_id) }}
                        />
                        <span className="flex-1 truncate">{b.bag_id}</span>
                        <span className="text-[11px] text-muted-foreground shrink-0">{b.sort_zone}</span>
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </div>

          <div className="border-t border-border px-3 py-1.5 flex items-center justify-between text-[10px] text-muted-foreground">
            <span>{matches.length} of {pool.length} unassigned</span>
            <span className="inline-flex items-center gap-1">
              <Check className="w-3 h-3" /> up/down then Enter
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
