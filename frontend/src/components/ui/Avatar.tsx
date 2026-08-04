import React from 'react';
import { useAuth } from '../../contexts/AuthContext';

/**
 * Field roles read from the generated role tokens (ADR-253) rather than from
 * `--slate`/`--teal`/`--warning`, which disagreed with both the token palette
 * and `pages/Register.tsx` — three systems, three different answers for what
 * colour a trainee is. `--trainee` was previously mapped to `--warning`, so a
 * trainee's avatar was literally the warning colour.
 *
 * Non-field roles (admin/management/dispatch) have no role token because they
 * are never shown in a field roster; they keep their semantic tokens.
 */
const ROLE_AVATAR: Record<string, { bg: string; text: string }> = {
  driver:      { bg: 'hsl(var(--driver) / 0.15)',  text: 'hsl(var(--driver))'  },
  walker:      { bg: 'hsl(var(--walker) / 0.15)',  text: 'hsl(var(--walker))'  },
  trainer:     { bg: 'hsl(var(--trainer) / 0.15)', text: 'hsl(var(--trainer))' },
  trainee:     { bg: 'hsl(var(--trainee) / 0.15)', text: 'hsl(var(--trainee))' },
  admin:       { bg: 'hsl(var(--neutral) / 0.15)', text: 'hsl(var(--neutral))' },
  management:  { bg: 'hsl(var(--primary) / 0.15)', text: 'hsl(var(--primary))' },
  dispatch:    { bg: 'hsl(var(--success) / 0.15)', text: 'hsl(var(--success))' },
  super_admin: { bg: 'hsl(var(--brand) / 0.15)',   text: 'hsl(var(--brand))'   },
};

export function getInitials(displayName?: string, username?: string): string {
  const name = displayName || username || '?';
  const parts = name.trim().split(/[\s._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

export default function Avatar({ size = 32 }: { size?: number }) {
  const { user, groups } = useAuth();
  const role = groups[0] ?? '';
  const colors = ROLE_AVATAR[role] ?? { bg: 'hsl(var(--accent))', text: 'hsl(var(--foreground))' };
  const initials = getInitials(user?.displayName, user?.username);
  return (
    <span
      style={{
        width: size,
        height: size,
        background: colors.bg,
        color: colors.text,
        fontSize: size * 0.38,
        borderRadius: '50%',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontWeight: 700,
        letterSpacing: '-0.01em',
        flexShrink: 0,
        border: `1.5px solid ${colors.text.replace(')', ' / 0.25)')}`,
      }}
    >
      {initials}
    </span>
  );
}
