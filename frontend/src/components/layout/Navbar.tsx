import React, { useState, useEffect, useRef } from 'react';
import { useNotificationContext } from '../../contexts/NotificationContext';
import type { Notification } from '../../contexts/NotificationContext';
import { TONE_TEXT } from '../notifications/tone';
import { NavLink, useNavigate, Link } from 'react-router-dom';
import { signOut } from 'aws-amplify/auth';
import { useAuth } from '../../contexts/AuthContext';
import {
  navItemsForGroups, homeRouteForGroups, HOME_ICON, type NavItem,
} from '../../config/navConfig';
import axiosClient from '../../api/axiosClient';
import {
  LogOut, Menu, X, Truck, AlertTriangle,
  Bell, Info, Search, UserCircle2,
} from 'lucide-react';
import ThemeToggle from '../ui/ThemeToggle';
import Avatar from '../ui/Avatar';

// ---------------------------------------------------------------------------
// Notification bell
// ---------------------------------------------------------------------------

/** The server's icon, tinted by the server's tone (ADR-487 D4).
 *
 *  This was the FIFTH copy of the same type-string guessing chain — alongside
 *  NotificationBanner, NotificationsHistory, and mobile's TYPE_META — and all
 *  five were worded slightly differently, so one notification could render as
 *  warning here and info two components away.
 *
 *  Two branches are not carried over, both dead:
 *    - `timecard_adjustment && VITE_ADP_ENABLED` — the flag is false in every
 *      .env, AND that string is never a notification type (every backend
 *      occurrence is a table name or an audit action_type).
 *    - `includes('critical')` — the guess that put an URGENT incident in the
 *      same bucket as a routine notice, which is the gap ADR-487 opens with.
 *
 *  The fallback is for the PlatformAlert-vocabulary types that reach this
 *  dropdown with no SPEC entry (ADR-324 D2 keeps the two apart), and for rows
 *  predating the registry.
 */
function notifIcon(n: Pick<Notification, 'type' | 'icon' | 'tone'>) {
  if (n.icon) {
    return (
      <span aria-hidden="true" className={`shrink-0 mt-0.5 text-sm ${TONE_TEXT[n.tone] ?? TONE_TEXT.neutral}`}>
        {n.icon}
      </span>
    );
  }
  if (n.type.endsWith('_failed')) return <AlertTriangle className="w-3.5 h-3.5 text-danger shrink-0 mt-0.5" />;
  return <Info className="w-3.5 h-3.5 text-info shrink-0 mt-0.5" />;
}

function NotificationDropdown({
  notifications,
  onMarkRead,
  onMarkAllRead,
  onClose,
}: {
  // Structural rather than the full `Notification`, so the caller is not forced
  // to supply fields this dropdown never reads. Widened by ADR-487 D4 with the
  // three the icon now needs — `tsc -b` caught the mismatch.
  notifications: (Pick<Notification, 'type' | 'icon' | 'tone'> &
    { id: string; message: string })[];
  onMarkRead: (id: string) => void;
  onMarkAllRead: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div
      ref={ref}
      className="absolute right-0 top-full mt-2 w-80 bg-card border border-border rounded-2xl shadow-lg shadow-black/10 z-50 overflow-hidden"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
        <span className="text-sm font-semibold text-foreground">Notifications</span>
        {notifications.length > 1 && (
          <button onClick={onMarkAllRead} className="text-xs text-muted-foreground hover:text-foreground underline transition-colors">
            Mark all read
          </button>
        )}
      </div>
      {notifications.length === 0 ? (
        <p className="px-4 py-6 text-sm text-center text-muted-foreground">You're all caught up.</p>
      ) : (
        <ul className="max-h-80 overflow-y-auto divide-y divide-border/40">
          {notifications.map(n => (
            <li key={n.id} className="flex items-start gap-3 px-4 py-3 hover:bg-accent/40 transition-colors">
              {notifIcon(n)}
              <p className="flex-1 text-xs text-foreground leading-snug">{n.message}</p>
              <button
                onClick={() => onMarkRead(n.id)}
                className="text-muted-foreground hover:text-foreground transition-colors shrink-0"
                title="Dismiss"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="border-t border-border/50 px-4 py-2">
        <Link
          to="/notifications"
          onClick={onClose}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          View all notifications →
        </Link>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Title bar — brand + user controls
// ---------------------------------------------------------------------------

function TitleBar() {
  const { user, groups } = useAuth();
  const navigate = useNavigate();
  const [bellOpen,    setBellOpen]    = useState(false);
  const [avatarOpen,  setAvatarOpen]  = useState(false);
  const avatarRef = useRef<HTMLDivElement>(null);
  const { notifications, markRead, markAllRead } = useNotificationContext();

  const handleSignOut = async () => {
    try {
      await signOut();
      navigate('/login');
    } catch (error) {
      console.error('Error signing out: ', error);
    }
  };

  // Close avatar dropdown on outside click
  useEffect(() => {
    if (!avatarOpen) return;
    const handler = (e: MouseEvent) => {
      if (avatarRef.current && !avatarRef.current.contains(e.target as Node)) {
        setAvatarOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [avatarOpen]);

  return (
    // `relative z-10` is load-bearing, not cosmetic. This bar and the nav strip
    // below are siblings, and BOTH create their own stacking context
    // (backdrop-blur here, .glass's backdrop-filter there). Painting then
    // follows DOM order, so the nav strip covered anything overflowing this bar
    // — the avatar and bell dropdowns were clipped behind it however high their
    // own z-index went, because a child cannot escape its parent's stacking
    // context. Lifting the whole bar fixes both dropdowns at once.
    <div className="relative z-10 w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-12 flex items-center justify-between gap-4">
        {/* Brand */}
        <div className="flex items-center gap-2 font-bold text-base tracking-tight shrink-0">
          <div className="flex items-center justify-center w-7 h-7 rounded-lg gradient-primary shadow-glow-primary">
            <Truck className="h-3.5 w-3.5 text-primary-foreground" />
          </div>
          <span className="font-display gradient-text-brand">AsheFlow</span>
        </div>

        {/* Right cluster — user + actions */}
        <div className="flex items-center gap-1.5">
          {/* Search / command palette */}
          <button
            onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))}
            className="hidden sm:inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border border-border
                       bg-surface text-muted-foreground hover:text-foreground hover:border-border-strong
                       transition-colors press text-xs"
            title="Open command palette"
          >
            <Search className="h-3 w-3" />
            <span className="hidden md:inline">Search</span>
            <span className="hidden lg:flex items-center gap-0.5 ml-1">
              <span className="kbd">⌘</span><span className="kbd">K</span>
            </span>
          </button>

          <ThemeToggle />

          {/* Notification bell */}
          <div className="relative">
            <button
              onClick={() => setBellOpen(o => !o)}
              className="relative inline-flex items-center justify-center w-8 h-8 rounded-lg
                         border border-border bg-surface text-muted-foreground
                         hover:text-foreground hover:border-border-strong transition-colors press"
              title="Notifications"
            >
              <Bell className="h-3.5 w-3.5" />
              {notifications.length > 0 && (
                <span className="absolute -top-1 -right-1 flex items-center justify-center min-w-4 h-4 px-1 rounded-full bg-danger text-danger-foreground text-[10px] font-bold leading-none shadow-glow-danger">
                  {notifications.length > 9 ? '9+' : notifications.length}
                </span>
              )}
            </button>
            {bellOpen && (
              <NotificationDropdown
                notifications={notifications}
                onMarkRead={id => { markRead(id); }}
                onMarkAllRead={() => { markAllRead(); setBellOpen(false); }}
                onClose={() => setBellOpen(false)}
              />
            )}
          </div>

          {/* Avatar dropdown */}
          <div className="relative ml-1" ref={avatarRef}>
            <button
              onClick={() => setAvatarOpen(o => !o)}
              className="flex items-center rounded-full focus:outline-none focus:ring-2 focus:ring-primary/40 press"
              title="Account"
            >
              <Avatar size={32} />
            </button>

            {avatarOpen && (
              <div className="absolute right-0 top-10 z-50 w-56 rounded-xl border border-border bg-card shadow-lg py-1 animate-slide-up">
                {/* Identity */}
                <div className="px-4 py-3 border-b border-border flex items-center gap-3">
                  <Avatar size={36} />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-foreground truncate">{user?.displayName || user?.username}</p>
                    <p className="text-xs text-muted-foreground capitalize">{groups[0]?.replace('_', ' ') ?? ''}</p>
                  </div>
                </div>
                {/* Actions */}
                <div className="py-1">
                  <Link
                    to="/account"
                    onClick={() => setAvatarOpen(false)}
                    className="flex items-center gap-2.5 px-4 py-2 text-sm text-foreground hover:bg-accent transition-colors"
                  >
                    <UserCircle2 className="w-4 h-4 text-muted-foreground" />
                    My Account
                  </Link>
                  <button
                    onClick={() => { setAvatarOpen(false); handleSignOut(); }}
                    className="w-full flex items-center gap-2.5 px-4 py-2 text-sm text-danger hover:bg-danger/5 transition-colors"
                  >
                    <LogOut className="w-4 h-4" />
                    Sign out
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Nav bar — links only, scrollable on overflow
// ---------------------------------------------------------------------------

const Navbar = () => {
  const { groups, isAuthenticated, hasFeature } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [trainerPhase, setTrainerPhase] = useState<number | null>(null);
  const [hasActiveQuiz, setHasActiveQuiz] = useState(false);

  // Only the two roles whose nav is fetched conditionally need a boolean here;
  // all tab visibility is now derived in navConfig (navItemsForGroups).
  const isTrainer = groups.includes('trainer');
  const isTrainee = groups.includes('trainee');

  useEffect(() => {
    if (!isAuthenticated || !isTrainer) return;
    axiosClient.get('/training/trainer/today')
      .then(res => setTrainerPhase(res.data?.record?.current_day_number ?? null))
      .catch(() => setTrainerPhase(null));
  }, [isAuthenticated, isTrainer]);

  useEffect(() => {
    if (!isAuthenticated || !isTrainee) return;
    axiosClient.get('/graduation-quiz/my-quiz')
      .then(() => setHasActiveQuiz(true))
      .catch(() => setHasActiveQuiz(false));
  }, [isAuthenticated, isTrainee]);

  const homeRoute = homeRouteForGroups(groups);

  // Config-driven nav: one source of truth for both desktop and mobile, and
  // the App.tsx route gates read the same role sets (see navConfig.ts).
  const navItems = navItemsForGroups(groups, { trainerPhase, hasActiveQuiz, hasFeature });

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all duration-200 press ${
      isActive
        ? 'bg-accent text-accent-foreground shadow-sm'
        : 'text-muted-foreground hover:text-foreground hover:bg-accent/60'
    }`;

  const links = (
    <>
      <NavLink to={homeRoute} end className={linkClass}><HOME_ICON className="w-3.5 h-3.5" /> Dashboard</NavLink>
      {navItems.map(item => (
        <NavLink key={item.path} to={item.path} end={item.path === '/dispatch'} className={linkClass}>
          <item.icon className="w-3.5 h-3.5" /> {item.label}
        </NavLink>
      ))}
    </>
  );

  return (
    <header className="sticky top-0 z-40">
      <TitleBar />

      {/* Nav strip */}
      <nav className="glass border-x-0 border-t-0 border-b border-border/60 rounded-none">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-10">

            {/* Desktop: scrollable link row */}
            <div className="hidden md:flex items-center min-w-0 flex-1">
              <div className="flex items-center gap-0.5 overflow-x-auto scrollbar-none pr-2">
                {links}
              </div>
            </div>

            {/* Mobile: hamburger */}
            <button
              onClick={() => setMobileOpen(o => !o)}
              className="md:hidden btn-ghost p-1.5"
            >
              <span className="sr-only">Toggle menu</span>
              {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </button>
          </div>
        </div>

        {/* Mobile menu */}
        {mobileOpen && (
          <div className="md:hidden animate-slide-up border-t border-border/50 bg-card">
            <div className="px-3 py-3 flex flex-col gap-0.5">
              <MobileLinks
                groups={groups}
                navItems={navItems}
                homeRoute={homeRoute}
                onNav={() => setMobileOpen(false)}
              />
            </div>
          </div>
        )}
      </nav>
    </header>
  );
};

function MobileLinks({
  groups, navItems, homeRoute, onNav,
}: {
  groups: string[];
  navItems: NavItem[];
  homeRoute: string;
  onNav: () => void;
}) {
  void groups;
  const cls = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
      isActive
        ? 'bg-accent text-accent-foreground shadow-sm'
        : 'text-muted-foreground hover:text-foreground hover:bg-accent/60'
    }`;

  return (
    <>
      <NavLink to={homeRoute} end onClick={onNav} className={cls}><HOME_ICON className="w-4 h-4" /> Dashboard</NavLink>
      {navItems.map(item => (
        <NavLink key={item.path} to={item.path} end={item.path === '/dispatch'} onClick={onNav} className={cls}>
          <item.icon className="w-4 h-4" /> {item.label}
        </NavLink>
      ))}
    </>
  );
}


export default Navbar;
