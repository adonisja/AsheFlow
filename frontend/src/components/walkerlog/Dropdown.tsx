import { Fragment, useEffect, useId, useMemo, useRef, useState } from 'react';
import { ChevronDown, Check, Search } from 'lucide-react';

/** The house dropdown for the walker log.
 *
 *  Every picker on this page had drifted to a different control: a native
 *  <select> here, a searchable popup there, an OS menu that covered the routes
 *  behind it. TotePicker and WalkerPicker already agreed on a shape — a bordered
 *  trigger, an overlay panel, a search box when the list is long, keyboard
 *  navigation, a check on the current value — and this generalises that shape so
 *  the remaining selects stop being the odd ones out.
 *
 *  Native <select> is not wrong everywhere; it is wrong HERE. Its popup renders
 *  outside the page's styling, cannot show a description under an option, and on
 *  a laptop opens a list that runs off the bottom of the viewport — all three of
 *  which this page hit.
 *
 *  `searchable` is automatic past a threshold rather than a prop everyone has to
 *  remember: a 4-option list with a search box is clutter, a 59-option list
 *  without one is unusable.
 */

export interface DropdownOption {
  value: string;
  label: string;
  /** Second line under the label — the reattemptable note, a sort zone. */
  description?: string;
  /** Right-aligned muted text: a count, a code, a zone. */
  hint?: string;
  /** A colour chip before the label (bag colours, difficulty scale). */
  swatch?: string;
  /** Optional heading this option sits under. Options carrying the same
   *  consecutive `group` render beneath one label — used for the building
   *  taxonomy, where Residential and Commercial are the first cut a collector
   *  makes. Purely presentational: the stored value is still the leaf. */
  group?: string;
  disabled?: boolean;
}

export default function Dropdown({
  value, options, placeholder, onChange, disabled, ariaLabel,
  align = 'left', className = '', searchThreshold = 8, widthClass = 'w-full',
}: {
  value: string;
  options: DropdownOption[];
  placeholder: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
  align?: 'left' | 'right';
  className?: string;
  /** Show the filter box once the list is at least this long. */
  searchThreshold?: number;
  /** Panel width. Defaults to matching the trigger. */
  widthClass?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const listId = useId();

  const searchable = options.length >= searchThreshold;

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    const terms = q.split(/\s+/);
    return options.filter((o) => {
      const hay = `${o.label} ${o.description ?? ''} ${o.hint ?? ''}`.toLowerCase();
      return terms.every((t) => hay.includes(t));
    });
  }, [options, query]);

  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open]);

  useEffect(() => {
    if (!open) { setQuery(''); return; }
    // Open ON the current value rather than at the top, so arrowing from a set
    // value moves from where you are instead of jumping to the first option.
    setCursor(Math.max(0, matches.findIndex((o) => o.value === value)));
    if (searchable) inputRef.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => { setCursor(0); }, [query]);

  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [cursor, open]);

  /** Open upward when there is not enough room below.
   *
   *  The panel used to always drop down. That was invisible while an ancestor
   *  card clipped it; once the clipping was removed the real behaviour showed
   *  — a picker near the bottom of a phone screen opened past the fold, so the
   *  last options could only be reached by scrolling the page while a menu was
   *  open. Measured on the Workload picker: the list's bottom sat below
   *  innerHeight with four options in it.
   *
   *  Decided at open time from the trigger's position, not on every scroll: a
   *  menu that flips while you are reaching for an option moves the target
   *  under your finger. */
  const [dropUp, setDropUp] = useState(false);
  useEffect(() => {
    if (!open) return;
    const r = boxRef.current?.getBoundingClientRect();
    if (!r) return;
    // 18rem panel cap + the search row + a little breathing room.
    const need = Math.min(340, 288 + (searchable ? 44 : 0)) + 12;
    const below = window.innerHeight - r.bottom;
    // Only flip when above is genuinely roomier — otherwise stay down, which
    // is what people expect.
    setDropUp(below < need && r.top > below);
  }, [open, searchable]);

  const choose = (o: DropdownOption) => {
    if (o.disabled) return;
    onChange(o.value);
    setOpen(false);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setCursor((c) => Math.min(c + 1, matches.length - 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    else if (e.key === 'Enter') { e.preventDefault(); if (matches[cursor]) choose(matches[cursor]); }
    else if (e.key === 'Escape') { e.preventDefault(); setOpen(false); }
    else if (e.key === 'Home') { e.preventDefault(); setCursor(0); }
    else if (e.key === 'End') { e.preventDefault(); setCursor(matches.length - 1); }
  };

  return (
    <div className={`relative ${className}`} ref={boxRef}>
      <button
        type="button"
        disabled={disabled}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => { if (!open && (e.key === 'ArrowDown' || e.key === 'Enter')) { e.preventDefault(); setOpen(true); } }}
        className="w-full flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm hover:border-primary/60 focus:outline-none focus:ring-2 focus:ring-primary/40 disabled:opacity-50 disabled:hover:border-border"
      >
        {selected?.swatch && (
          <span aria-hidden className="w-2.5 h-2.5 rounded-full ring-1 ring-black/10 shrink-0"
            style={{ background: selected.swatch }} />
        )}
        <span className={`flex-1 text-left truncate ${selected ? '' : 'text-muted-foreground'}`}>
          {selected ? selected.label : placeholder}
        </span>
        {selected?.hint && <span className="text-xs text-muted-foreground shrink-0">{selected.hint}</span>}
        <ChevronDown className={`w-4 h-4 text-muted-foreground shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className={`absolute ${align === 'right' ? 'right-0' : 'left-0'} ${dropUp ? 'bottom-full mb-1.5' : 'top-full mt-1.5'} z-40 ${widthClass} min-w-[12rem] max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card shadow-lg overflow-hidden`}>
          {searchable && (
            <div className="relative border-b border-border">
              <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <input
                ref={inputRef} value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKey}
                placeholder="Filter"
                className="w-full bg-transparent pl-9 pr-3 py-2.5 text-sm outline-none"
              />
            </div>
          )}

          <div
            ref={listRef} id={listId} role="listbox" tabIndex={searchable ? -1 : 0}
            onKeyDown={searchable ? undefined : onKey}
            className="max-h-72 overflow-y-auto py-1 focus:outline-none"
          >
            {matches.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">No match.</p>
            ) : matches.map((o, i) => (
              /* A heading whenever the group CHANGES, so filtering cannot leave
                 an orphaned header over options from the next group. The
                 headings sit outside the option list for keyboard purposes —
                 `cursor` still indexes `matches`, so arrowing skips them. */
              <Fragment key={o.value}>
                {o.group && o.group !== matches[i - 1]?.group && (
                  <p className="px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70">
                    {o.group}
                  </p>
                )}
              <button
                type="button"
                role="option"
                aria-selected={o.value === value}
                data-active={i === cursor}
                disabled={o.disabled}
                onMouseEnter={() => setCursor(i)}
                onClick={() => choose(o)}
                className={`w-full flex items-start gap-2 px-3 py-2 text-left text-sm ${
                  i === cursor ? 'bg-accent/60' : ''
                } ${o.disabled ? 'opacity-40 cursor-not-allowed' : ''}`}
              >
                <span className="w-3.5 shrink-0 pt-0.5">
                  {o.value === value && <Check className="w-3.5 h-3.5" />}
                </span>
                {o.swatch && (
                  <span aria-hidden className="w-2.5 h-2.5 rounded-full ring-1 ring-black/10 shrink-0 mt-1"
                    style={{ background: o.swatch }} />
                )}
                <span className="flex-1 min-w-0">
                  <span className="block truncate">{o.label}</span>
                  {o.description && (
                    <span className="block text-[11px] text-muted-foreground">{o.description}</span>
                  )}
                </span>
                {o.hint && <span className="text-[11px] text-muted-foreground shrink-0 pt-0.5">{o.hint}</span>}
              </button>
              </Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
