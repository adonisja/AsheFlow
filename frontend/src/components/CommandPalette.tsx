import React, { useEffect, useState, useMemo } from 'react';
import { Command } from 'cmdk';
import { useNavigate } from 'react-router-dom';
import { signOut } from 'aws-amplify/auth';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Home, Calendar, Settings, ClipboardCheck, Users, MapPin,
  AlertTriangle, Shield, RefreshCw, ShieldAlert, Star, LogOut,
  Moon, Sun, Search, MessageSquare,
} from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../contexts/ThemeContext';

interface Action {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  group: string;
  perform: () => void;
  visible?: boolean;
  keywords?: string;
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const navigate = useNavigate();
  const { groups } = useAuth();
  const { theme, toggleTheme } = useTheme();

  // Toggle on ⌘K / Ctrl+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen(o => !o);
      }
      if (e.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const isFieldStaff = groups.some((r: string) => ['driver', 'walker', 'trainer', 'trainee'].includes(r));
  const isAdmin      = groups.includes('admin');
  const isDispatch   = groups.includes('dispatch');
  const isMgmt       = groups.includes('management');

  const homeRoute = useMemo(() => {
    if (isAdmin)    return '/admin';
    if (isDispatch) return '/dispatch-home';
    if (isMgmt)     return '/management';
    if (groups.includes('trainer')) return '/trainer-dashboard';
    if (groups.includes('trainee')) return '/my-training';
    return '/';
  }, [groups, isAdmin, isDispatch, isMgmt]);

  const close = () => { setOpen(false); setQuery(''); };
  const go = (path: string) => { close(); navigate(path); };

  const actions: Action[] = [
    { id: 'home', label: 'Home', icon: Home, group: 'Navigation', perform: () => go(homeRoute), visible: true },
    { id: 'schedule', label: 'Schedule', icon: Calendar, group: 'Navigation',
      perform: () => go('/schedule'),
      visible: isFieldStaff || isMgmt || isAdmin },
    { id: 'preferences', label: 'Preferences', icon: Settings, group: 'Navigation',
      perform: () => go('/preferences'), visible: isFieldStaff || isAdmin },
    { id: 'schedule-changes', label: 'Schedule Changes', icon: RefreshCw, group: 'Navigation',
      perform: () => go('/schedule-changes'),
      visible: isFieldStaff || isDispatch || isAdmin },
    { id: 'field-ops', label: 'Field Ops', icon: MapPin, group: 'Navigation',
      perform: () => go('/field-ops'), visible: isFieldStaff || isAdmin },
    { id: 'incidents', label: 'Incidents', icon: AlertTriangle, group: 'Navigation', perform: () => go('/incidents'), visible: true },
    { id: 'dispatch', label: 'Dispatch', icon: ClipboardCheck, group: 'Navigation',
      perform: () => go('/dispatch'), visible: isAdmin || isDispatch },
    { id: 'assets', label: 'Assets', icon: Users, group: 'Management',
      perform: () => go('/assets'), visible: isAdmin || isMgmt },
    { id: 'trainees', label: 'Trainees', icon: ClipboardCheck, group: 'Management',
      perform: () => go('/trainee-management'), visible: isAdmin || isMgmt },
    { id: 'compliance', label: 'Vehicle Compliance', icon: ShieldAlert, group: 'Management',
      perform: () => go('/vehicle-compliance'), visible: isAdmin || isMgmt },
    { id: 'walkers', label: 'Walker Performance', icon: Star, group: 'Management',
      perform: () => go('/walker-performance'), visible: isAdmin || isMgmt },
    { id: 'feedback', label: 'Feedback Inbox', icon: MessageSquare, group: 'Management',
      perform: () => go('/feedback'), visible: isAdmin },
    { id: 'admin', label: 'Admin Console', icon: Shield, group: 'Management',
      perform: () => go('/admin'), visible: isAdmin },
    { id: 'theme', label: theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode',
      icon: theme === 'dark' ? Sun : Moon, group: 'Preferences',
      perform: () => { toggleTheme(); close(); }, visible: true,
      keywords: 'theme dark light mode color' },
    { id: 'signout', label: 'Sign out', icon: LogOut, group: 'Account',
      perform: async () => { close(); await signOut().catch(() => {}); navigate('/login'); }, visible: true },
  ];

  const visibleActions = actions.filter(a => a.visible);
  const grouped = visibleActions.reduce<Record<string, Action[]>>((acc, a) => {
    (acc[a.group] = acc[a.group] || []).push(a);
    return acc;
  }, {});

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-[100] flex items-start justify-center pt-[12vh] px-4"
          onClick={close}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-foreground/30 backdrop-blur-md" />

          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: -8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.97, y: -4 }}
            transition={{ type: 'spring', stiffness: 400, damping: 30 }}
            className="relative w-full max-w-xl glass-strong rounded-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <Command label="Command palette" className="flex flex-col">
              <div className="flex items-center gap-3 px-4 py-3.5 border-b border-border/60">
                <Search className="w-4 h-4 text-muted-foreground shrink-0" />
                <Command.Input
                  value={query}
                  onValueChange={setQuery}
                  placeholder="Search pages, actions, settings…"
                  className="flex-1 bg-transparent outline-none text-sm text-foreground placeholder:text-muted-foreground"
                  autoFocus
                />
                <span className="kbd">esc</span>
              </div>

              <Command.List className="max-h-[60vh] overflow-y-auto p-2">
                <Command.Empty className="py-10 text-center text-sm text-muted-foreground">
                  No matches found.
                </Command.Empty>

                {Object.entries(grouped).map(([group, items]) => (
                  <Command.Group
                    key={group}
                    heading={group}
                    className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground px-2 pt-3 pb-1 font-semibold
                               [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5"
                  >
                    {items.map(a => (
                      <Command.Item
                        key={a.id}
                        value={`${a.label} ${a.keywords || ''}`}
                        onSelect={a.perform}
                        className="group flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm text-foreground cursor-pointer
                                   data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground
                                   transition-colors"
                      >
                        <a.icon className="w-4 h-4 text-muted-foreground group-data-[selected=true]:text-accent-foreground" />
                        <span className="flex-1">{a.label}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                ))}
              </Command.List>

              <div className="flex items-center justify-between px-4 py-2.5 border-t border-border/60 bg-surface-muted/40">
                <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                  <span className="kbd">↑</span><span className="kbd">↓</span>
                  <span>navigate</span>
                  <span className="kbd">↵</span>
                  <span>select</span>
                </div>
                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span className="kbd">⌘</span><span className="kbd">K</span>
                  <span>toggle</span>
                </div>
              </div>
            </Command>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
