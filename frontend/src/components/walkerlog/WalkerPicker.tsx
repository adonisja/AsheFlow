import { useEffect, useMemo, useRef, useState } from 'react';
import { UserPlus, Search, X, Check, Clock } from 'lucide-react';

/** Picks the walker who takes a route, and can add one who is not on the list.
 *
 *  Replaces a native <select> that had two problems. The visible one was UI: an
 *  unsearchable OS dropdown that covered the routes behind it. The real one was
 *  that it could only ever offer names it already knew — the seeded crew, or
 *  someone with a saved day. On any date without a seed that list is EMPTY, so
 *  there was no way to name a walker at all, and no way to correct a name once
 *  entered.
 *
 *  So this is a combobox, not a menu: type a name and either match someone or
 *  create them. Sections are ordered by how likely they are to be the answer —
 *  today's crew first, then people who have walked before (they come back on
 *  later days), then the escape hatch of a brand-new name.
 */
export default function WalkerPicker({
  crew, previous, value, placeholder, onPick, onAddToCrew, onRemoveFromCrew, align = 'left',
}: {
  /** Walkers on today's truck — the expected answer, listed first. */
  crew: string[];
  /** Everyone logged on any earlier date, minus today's crew. */
  previous: string[];
  /** Current selection, shown on the trigger. '' renders the placeholder. */
  value?: string;
  placeholder: string;
  onPick: (name: string) => void;
  /** Present only where adding to the crew makes sense (the crew editor). */
  onAddToCrew?: (name: string) => void;
  onRemoveFromCrew?: (name: string) => void;
  align?: 'left' | 'right';
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const boxRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const q = query.trim();
  const lower = q.toLowerCase();
  const match = (n: string) => n.toLowerCase().includes(lower);

  const crewHits = useMemo(() => crew.filter(match), [crew, lower]);
  const prevHits = useMemo(() => previous.filter(match), [previous, lower]);

  /** Offer "add" only for a genuinely new name — an exact match anywhere means
   *  they already exist and picking them is the right action, not creating a
   *  duplicate that differs only by case. */
  const exists = [...crew, ...previous].some((n) => n.toLowerCase() === lower);
  const canCreate = q.length > 0 && !exists;

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

  const choose = (name: string) => {
    onPick(name);
    setQuery('');
    setOpen(false);
  };

  const create = () => {
    if (!canCreate) return;
    onAddToCrew?.(q);
    onPick(q);
    setQuery('');
    setOpen(false);
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); setOpen(false); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      // First exact-ish match wins; otherwise create. Enter should never be a
      // no-op when the box has text in it.
      const first = crewHits[0] ?? prevHits[0];
      if (first) choose(first);
      else create();
    }
  };

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="w-full flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm hover:border-primary/60 focus:outline-none focus:ring-2 focus:ring-primary/40"
      >
        <span className={`flex-1 text-left truncate ${value ? '' : 'text-muted-foreground'}`}>
          {value || placeholder}
        </span>
        <UserPlus className="w-4 h-4 text-muted-foreground shrink-0" />
      </button>

      {open && (
        <div className={`absolute ${align === 'right' ? 'right-0' : 'left-0'} z-40 mt-1.5 w-[20rem] max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-card shadow-lg overflow-hidden`}>
          <div className="relative border-b border-border">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onKey}
              placeholder="Search or type a new name"
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

          <div className="max-h-72 overflow-y-auto py-1" role="listbox">
            {crewHits.length > 0 && (
              <Section label="On the truck today">
                {crewHits.map((n) => (
                  <Row
                    key={n} name={n} selected={n === value}
                    onPick={() => choose(n)}
                    onRemove={onRemoveFromCrew ? () => onRemoveFromCrew(n) : undefined}
                  />
                ))}
              </Section>
            )}

            {prevHits.length > 0 && (
              <Section label="Walked before">
                {prevHits.map((n) => (
                  <Row
                    key={n} name={n} selected={n === value} muted
                    onPick={() => choose(n)}
                    onAdd={onAddToCrew ? () => { onAddToCrew(n); } : undefined}
                  />
                ))}
              </Section>
            )}

            {canCreate && (
              <button
                type="button" onClick={create}
                className="w-full flex items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent/40 border-t border-border"
              >
                <UserPlus className="w-3.5 h-3.5 text-primary shrink-0" />
                <span>Add <strong>{q}</strong></span>
                {onAddToCrew && <span className="ml-auto text-[11px] text-muted-foreground">to today's crew</span>}
              </button>
            )}

            {crewHits.length === 0 && prevHits.length === 0 && !canCreate && (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                No walkers yet. Type a name to add one.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      {children}
    </div>
  );
}

function Row({ name, selected, muted, onPick, onAdd, onRemove }: {
  name: string;
  selected?: boolean;
  muted?: boolean;
  onPick: () => void;
  onAdd?: () => void;
  onRemove?: () => void;
}) {
  return (
    <div className={`group flex items-center gap-1 ${selected ? 'bg-accent/60' : 'hover:bg-accent/40'}`}>
      <button type="button" onClick={onPick} role="option" aria-selected={!!selected}
        className="flex-1 flex items-center gap-2 px-3 py-1.5 text-left text-sm min-w-0">
        {muted ? <Clock className="w-3 h-3 text-muted-foreground shrink-0" />
               : <span className="w-3 shrink-0">{selected && <Check className="w-3 h-3" />}</span>}
        <span className="truncate">{name}</span>
      </button>
      {onAdd && (
        <button type="button" onClick={onAdd} title="Add to today's crew"
          className="px-2 py-1 text-[11px] text-muted-foreground hover:text-primary shrink-0">
          + crew
        </button>
      )}
      {onRemove && (
        <button type="button" onClick={onRemove} title="Remove from today's crew"
          className="px-2 py-1 text-muted-foreground hover:text-danger shrink-0 opacity-0 group-hover:opacity-100 focus:opacity-100">
          <X className="w-3.5 h-3.5" />
        </button>
      )}
    </div>
  );
}
