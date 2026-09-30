import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ChevronDown } from 'lucide-react';

export interface SelectOption {
  value: string;
  label: string;
  /** Small muted text after the label — a role, a status, a reason. */
  hint?: string;
  /** Rendered before the label. Used to mark hub trucks. */
  icon?: ReactNode;
  disabled?: boolean;
  /** Non-selectable heading. Groups a run of options under a role or category. */
  header?: boolean;
}

/**
 * Single-select in the house dropdown style — the one the truck picker on the
 * assignments board uses: a bordered trigger button and an overlaid panel,
 * rather than a native <select>.
 *
 * A native select cannot show an icon per option, cannot group with a visible
 * heading, and renders differently on every platform. Those matter here: hub
 * trucks need a marker, and the employee list is only legible grouped by role.
 *
 * Closes on outside click and Escape, like the picker it mirrors — a panel that
 * overlays other controls and traps the pointer is worse than a native select,
 * not better.
 */
export default function SelectMenu({
  value, options, placeholder, onChange, icon, ariaLabel, portal = false,
}: {
  value: string;
  options: SelectOption[];
  placeholder: string;
  onChange: (v: string) => void;
  icon?: ReactNode;
  ariaLabel?: string;
  /**
   * Render the panel into document.body at a fixed position instead of
   * absolutely inside this element (ADR-484 D3).
   *
   * The default `absolute` panel is clipped by any ancestor with
   * `overflow-auto`/`hidden` — a scrolling table body, a modal with its own
   * scroll region. A native select never had this problem, because its popup is
   * drawn by the OS outside the page box. So a scroll container is exactly the
   * place where replacing one makes things WORSE unless this is set.
   *
   * Not the default: a fixed panel cannot follow its trigger, so it is only
   * right where the alternative is being cut off.
   */
  portal?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [rect, setRect] = useState<{ top: number; left: number; width: number } | null>(null);

  // Measured before paint, so a portalled panel never shows at the wrong spot
  // for one frame before settling.
  useLayoutEffect(() => {
    if (!open || !portal || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    setRect({ top: r.bottom + 4, left: r.left, width: r.width });
  }, [open, portal]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false); };
    // A fixed panel cannot follow its trigger, so scrolling must dismiss it
    // rather than leave it stranded mid-page. Capture phase: the scroll usually
    // happens on an inner container, not window.
    const onScroll = () => { if (portal) setOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    window.addEventListener('scroll', onScroll, true);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('scroll', onScroll, true);
    };
  }, [open, portal]);

  const selected = options.find(o => o.value === value && !o.header);

  // Built once and rendered either in place or through a portal, so the two
  // modes cannot drift apart on a later edit.
  const panel = (
    <div
      role="listbox"
      style={portal && rect
        ? { position: 'fixed', top: rect.top, left: rect.left, width: rect.width }
        : undefined}
      className={portal
        ? 'z-50 max-h-72 overflow-auto rounded-lg border border-border bg-card shadow-lg'
        : 'absolute z-20 mt-1 w-full max-h-72 overflow-auto rounded-lg border border-border bg-card shadow-lg'}
    >
      {options.length === 0 ? (
        <p className="px-3 py-3 text-xs text-muted-foreground">Nothing to choose.</p>
      ) : options.map(o => o.header ? (
        <div
          key={`h-${o.value}`}
          className="px-3 pt-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground"
        >
          {o.label}
        </div>
      ) : (
        <button
          key={o.value}
          type="button"
          role="option"
          aria-selected={o.value === value}
          disabled={o.disabled}
          onClick={() => { onChange(o.value); setOpen(false); }}
          className={`w-full flex items-center gap-2 px-3 py-2 text-left text-sm ${
            o.disabled
              ? 'opacity-40 cursor-not-allowed'
              : 'hover:bg-accent/40 cursor-pointer'
          } ${o.value === value ? 'bg-accent/60' : ''}`}
        >
          {o.icon}
          <span className="truncate flex-1">{o.label}</span>
          {o.hint && <span className="text-xs text-muted-foreground shrink-0">{o.hint}</span>}
        </button>
      ))}
    </div>
  );

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 rounded-xl border border-input bg-background px-3 py-2 text-sm shadow-sm hover:border-primary focus:ring-1 focus:ring-primary outline-none"
      >
        {icon}
        <span className={`flex-1 text-left truncate ${selected ? '' : 'text-muted-foreground'}`}>
          {selected ? selected.label : placeholder}
        </span>
        {selected?.hint && (
          <span className="text-xs text-muted-foreground shrink-0">{selected.hint}</span>
        )}
        <ChevronDown className={`w-4 h-4 text-muted-foreground shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (portal ? createPortal(panel, document.body) : panel)}
    </div>
  );
}
