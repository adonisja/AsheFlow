import React from 'react';
import { useAuth } from '../../contexts/AuthContext';

const ROLE_AVATAR: Record<string, { bg: string; text: string }> = {
  driver:      { bg: 'hsl(var(--slate) / 0.15)',   text: 'hsl(var(--slate))'   },
  walker:      { bg: 'hsl(var(--teal) / 0.15)',    text: 'hsl(var(--teal))'    },
  trainer:     { bg: 'hsl(var(--gold) / 0.15)',    text: 'hsl(var(--gold))'    },
  trainee:     { bg: 'hsl(var(--warning) / 0.15)', text: 'hsl(var(--warning))' },
  admin:       { bg: 'hsl(var(--neutral) / 0.15)', text: 'hsl(var(--neutral))' },
  management:  { bg: 'hsl(var(--primary) / 0.15)', text: 'hsl(var(--primary))' },
  dispatch:    { bg: 'hsl(var(--success) / 0.15)', text: 'hsl(var(--success))' },
  super_admin: { bg: 'hsl(265 70% 55% / 0.15)',    text: 'hsl(265 70% 55%)'    },
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
