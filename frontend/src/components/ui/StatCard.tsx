import React from 'react';
import { motion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';

type Tone = 'primary' | 'success' | 'warning' | 'danger' | 'info' | 'gold' | 'violet' | 'teal';

interface Props {
  label: string;
  value: React.ReactNode;
  icon: LucideIcon;
  tone?: Tone;
  delay?: number;
  hint?: string;
}

const toneStyles: Record<Tone, { icon: string; chip: string }> = {
  primary: { icon: 'text-primary',  chip: 'bg-primary/10' },
  success: { icon: 'text-success',  chip: 'bg-success/10' },
  warning: { icon: 'text-warning',  chip: 'bg-warning/10' },
  danger:  { icon: 'text-danger',   chip: 'bg-danger/10' },
  info:    { icon: 'text-info',     chip: 'bg-info/10' },
  gold:    { icon: 'text-gold',     chip: 'bg-gold/10' },
  violet:  { icon: 'text-violet',   chip: 'bg-violet/10' },
  teal:    { icon: 'text-teal',     chip: 'bg-teal/10' },
};

export default function StatCard({ label, value, icon: Icon, tone = 'primary', delay = 0, hint }: Props) {
  const styles = toneStyles[tone];
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay, ease: [0.22, 1, 0.36, 1] }}
      whileHover={{ y: -3, transition: { type: 'spring', stiffness: 400, damping: 22 } }}
      className="card-elevated flex items-center gap-4"
    >
      <div className={`flex items-center justify-center w-11 h-11 rounded-xl ${styles.chip}`}>
        <Icon className={`w-5 h-5 ${styles.icon}`} />
      </div>
      <div className="min-w-0">
        <p className="text-[11px] text-muted-foreground uppercase tracking-[0.12em] font-semibold">{label}</p>
        <p className="text-sm font-semibold text-foreground mt-1 truncate">{value}</p>
        {hint && <p className="text-xs text-muted-foreground mt-0.5">{hint}</p>}
      </div>
    </motion.div>
  );
}
