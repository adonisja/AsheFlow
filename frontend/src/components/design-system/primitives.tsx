import { type LucideIcon } from 'lucide-react';

// ─── Avatar ───────────────────────────────────────────────────────────────────

type Role = 'driver' | 'walker' | 'trainer' | 'trainee' | 'default';

const roleTones: Record<Role, { bg: string; fg: string }> = {
  driver:  { bg: 'hsl(var(--slate) / 0.16)',   fg: 'hsl(var(--slate))' },
  walker:  { bg: 'hsl(var(--teal) / 0.16)',    fg: 'hsl(var(--teal))' },
  trainer: { bg: 'hsl(var(--gold) / 0.16)',    fg: 'hsl(var(--gold))' },
  trainee: { bg: 'hsl(var(--warning) / 0.18)', fg: 'hsl(var(--warning))' },
  default: { bg: 'hsl(var(--primary) / 0.16)', fg: 'hsl(var(--primary))' },
};

interface AvatarProps {
  initials: string;
  role?: Role;
  size?: number;
}

export function Avatar({ initials, role = 'default', size = 28 }: AvatarProps) {
  const t = roleTones[role] ?? roleTones.default;
  const fontSize = size <= 24 ? 9 : size <= 30 ? 10 : 11;
  return (
    <span
      style={{
        width: size, height: size, borderRadius: 999,
        background: t.bg, color: t.fg,
        display: 'inline-grid', placeItems: 'center',
        fontWeight: 700, fontSize, flexShrink: 0,
        fontFamily: 'var(--font-sans)',
      }}
    >
      {initials}
    </span>
  );
}

// ─── Badge ────────────────────────────────────────────────────────────────────

type BadgeTone = 'success' | 'warning' | 'danger' | 'info' | 'slate' | 'gold' | 'teal' | 'neutral' | 'muted';

const badgeTones: Record<BadgeTone, [string, string]> = {
  success: ['hsl(var(--success))', 'hsl(var(--success) / 0.1)'],
  warning: ['hsl(var(--warning))', 'hsl(var(--warning) / 0.12)'],
  danger:  ['hsl(var(--danger))',  'hsl(var(--danger) / 0.1)'],
  info:    ['hsl(var(--info))',    'hsl(var(--info) / 0.1)'],
  slate:   ['hsl(var(--slate))',   'hsl(var(--slate) / 0.1)'],
  gold:    ['hsl(var(--gold))',    'hsl(var(--gold) / 0.14)'],
  teal:    ['hsl(var(--teal))',    'hsl(var(--teal) / 0.12)'],
  neutral: ['hsl(var(--neutral))', 'hsl(var(--neutral) / 0.1)'],
  muted:   ['hsl(var(--muted-foreground))', 'hsl(var(--muted))'],
};

interface BadgeProps {
  tone?: BadgeTone;
  children: React.ReactNode;
  dot?: boolean;
}

export function Badge({ tone = 'muted', children, dot = false }: BadgeProps) {
  const [fg, bg] = badgeTones[tone] ?? badgeTones.muted;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px', borderRadius: 8,
      fontSize: 11.5, fontWeight: 500,
      color: fg, background: bg,
    }}>
      {dot && <span style={{ width: 6, height: 6, borderRadius: 999, background: 'currentColor' }} />}
      {children}
    </span>
  );
}

// ─── Status badge ─────────────────────────────────────────────────────────────

type AssignmentStatus = 'confirmed' | 'pending' | 'declined' | 'assigned';

const statusMap: Record<AssignmentStatus, [BadgeTone, string]> = {
  confirmed: ['success', 'Confirmed'],
  pending:   ['warning', 'Pending'],
  declined:  ['danger',  'Declined'],
  assigned:  ['info',    'Assigned'],
};

export function StatusBadge({ status }: { status: AssignmentStatus }) {
  const [tone, label] = statusMap[status] ?? ['muted', status];
  return <Badge tone={tone} dot>{label}</Badge>;
}

// ─── Role badge ───────────────────────────────────────────────────────────────
// Color mapping (approved): driver=slate, walker=teal, trainer=gold, trainee=warning, admin=neutral
// Admin uses neutral because it is an access level, not an operational role.

type EmployeeRole = 'driver' | 'walker' | 'trainer' | 'trainee' | 'admin';

const roleMap: Record<EmployeeRole, BadgeTone> = {
  driver:  'slate',
  walker:  'teal',
  trainer: 'gold',
  trainee: 'warning',
  admin:   'neutral',
};

export function RoleBadge({ role }: { role: EmployeeRole }) {
  return <Badge tone={roleMap[role] ?? 'muted'}>{role}</Badge>;
}

// ─── StatCard ─────────────────────────────────────────────────────────────────
// All stat cards use the same min-height (88px) — equalizes cards with and without hint text.
// Hint text slot is always rendered (empty string when unused) to prevent layout shift.
// Never reduce font size to fit a fixed height — font size is semantic.

type StatTone = 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'gold' | 'slate' | 'teal';

const statTones: Record<StatTone, string> = {
  primary: 'hsl(var(--primary))',
  success: 'hsl(var(--success))',
  warning: 'hsl(var(--warning))',
  danger:  'hsl(var(--danger))',
  info:    'hsl(var(--info))',
  gold:    'hsl(var(--gold))',
  slate:   'hsl(var(--slate))',
  teal:    'hsl(var(--teal))',
};

interface StatCardProps {
  label: string;
  value: string | number;
  icon: LucideIcon;
  tone?: StatTone;
  hint?: string;
  delay?: number;
}

export function StatCard({ label, value, icon: Icon, tone = 'primary', hint, delay = 0 }: StatCardProps) {
  const color = statTones[tone];
  return (
    <div
      className="stat-card"
      style={{ animation: `afFadeUp 0.55s cubic-bezier(.22,1,.36,1) ${delay}s both` }}
    >
      <div style={{
        width: 44, height: 44, borderRadius: 12,
        display: 'grid', placeItems: 'center', flexShrink: 0,
        background: `${color.replace(')', ' / 0.1)')}`, color,
      }}>
        <Icon size={20} />
      </div>
      <div style={{ minWidth: 0 }}>
        <p className="eyebrow" style={{ margin: 0 }}>{label}</p>
        <p style={{
          fontFamily: 'var(--font-display)', fontSize: 26, fontWeight: 700,
          letterSpacing: '-0.025em', color: 'hsl(var(--foreground))',
          margin: '4px 0 0', lineHeight: 1,
        }}>{value}</p>
        {/* Always render hint slot to keep card height stable */}
        <p style={{ fontSize: 11, color: 'hsl(var(--muted-foreground))', margin: '4px 0 0', minHeight: '1em' }}>
          {hint ?? ''}
        </p>
      </div>
    </div>
  );
}

// ─── SectionHeader ───────────────────────────────────────────────────────────

interface SectionHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}

export function SectionHeader({ eyebrow, title, description, actions }: SectionHeaderProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
      <div style={{ minWidth: 0 }}>
        {eyebrow && <p className="eyebrow" style={{ margin: '0 0 6px' }}>{eyebrow}</p>}
        <h1 className="page-title" style={{ margin: 0 }}>{title}</h1>
        {description && <p className="text-subtle" style={{ margin: '8px 0 0', maxWidth: 640 }}>{description}</p>}
      </div>
      {actions && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          {actions}
        </div>
      )}
    </div>
  );
}

// ─── Card ────────────────────────────────────────────────────────────────────

interface CardProps {
  children: React.ReactNode;
  className?: string;
  padding?: number;
  hoverable?: boolean;
  style?: React.CSSProperties;
}

export function Card({ children, className = '', padding = 20, hoverable = false, style = {} }: CardProps) {
  return (
    <div
      className={`card${hoverable ? ' card-elevated' : ''}${className ? ` ${className}` : ''}`}
      style={{ padding, ...style }}
    >
      {children}
    </div>
  );
}

// ─── Kbd ─────────────────────────────────────────────────────────────────────
// Platform-aware: shows ⌘ on Mac, Ctrl on Windows/Linux.
// Use <Kbd modifier /> for the modifier key, <Kbd>K</Kbd> for letter keys.

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

interface KbdProps {
  children?: React.ReactNode;
  modifier?: boolean;
}

export function Kbd({ children, modifier = false }: KbdProps) {
  const content = modifier ? (isMac ? '⌘' : 'Ctrl') : children;
  return <span className="kbd">{content}</span>;
}

// ─── Eyebrow ─────────────────────────────────────────────────────────────────

export function Eyebrow({ children }: { children: React.ReactNode }) {
  return <p className="eyebrow" style={{ margin: '0 0 8px' }}>{children}</p>;
}

// ─── IconButton ──────────────────────────────────────────────────────────────

interface IconButtonProps {
  icon: LucideIcon;
  onClick?: () => void;
  title?: string;
  badge?: number;
  style?: React.CSSProperties;
}

export function IconButton({ icon: Icon, onClick, title, badge, style = {} }: IconButtonProps) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        width: 30, height: 30, borderRadius: 8,
        border: '1px solid hsl(var(--border))',
        background: 'hsl(var(--surface))',
        color: 'hsl(var(--muted-foreground))',
        display: 'inline-grid', placeItems: 'center',
        position: 'relative', cursor: 'pointer',
        ...style,
      }}
    >
      <Icon size={14} />
      {badge != null && badge > 0 && (
        <span style={{
          position: 'absolute', top: -4, right: -4,
          minWidth: 16, height: 16, padding: '0 4px',
          background: 'hsl(var(--danger))', color: 'white',
          fontSize: 9, fontWeight: 700, borderRadius: 999,
          display: 'grid', placeItems: 'center',
          boxShadow: '0 0 24px -6px hsl(var(--danger) / 0.5)',
        }}>{badge > 9 ? '9+' : badge}</span>
      )}
    </button>
  );
}
