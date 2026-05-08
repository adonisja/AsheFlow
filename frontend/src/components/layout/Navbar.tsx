import React, { useState, useEffect, useRef, useCallback } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { signOut } from 'aws-amplify/auth';
import { useAuth } from '../../contexts/AuthContext';
import axiosClient from '../../api/axiosClient';
import {
  LogOut,
  Menu,
  X,
  Home,
  Calendar,
  Settings,
  Truck,
  ClipboardCheck,
  Users,
  MapPin,
  AlertTriangle,
  Shield,
  RefreshCw,
  ShieldAlert,
  MessageSquare,
  Star,
  Bell,
  CheckCircle2,
  XCircle,
  Info,
  Search,
  BarChart2,
} from 'lucide-react';
import ThemeToggle from '../ui/ThemeToggle';

// ---------------------------------------------------------------------------
// Notification bell
// ---------------------------------------------------------------------------

interface NavNotification {
  id: string;
  type: string;
  message: string;
  is_read: boolean;
  created_at: string;
}

function notifIcon(type: string) {
  if (type.endsWith('_approved')) return <CheckCircle2 className="w-3.5 h-3.5 text-success shrink-0 mt-0.5" />;
  if (type.endsWith('_rejected')) return <XCircle className="w-3.5 h-3.5 text-danger shrink-0 mt-0.5" />;
  if (type.includes('critical') || type.includes('warning')) return <AlertTriangle className="w-3.5 h-3.5 text-warning shrink-0 mt-0.5" />;
  return <Info className="w-3.5 h-3.5 text-info shrink-0 mt-0.5" />;
}

const EMPLOYEE_GROUPS = ['driver', 'walker', 'trainer', 'trainee'];

function useNotifications(isAuthenticated: boolean, groups: string[]) {
  const [employeeId, setEmployeeId] = useState<string | null>(null);
  const [notifications, setNotifications] = useState<NavNotification[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isFieldStaffOrDispatch = groups.some(g => [...EMPLOYEE_GROUPS, 'dispatch'].includes(g));

  const fetchNotifs = useCallback(async (empId: string) => {
    try {
      const res = await axiosClient.get<NavNotification[]>(`/notifications/${empId}`, { params: { limit: 20 } });
      setNotifications(res.data.filter(n => !n.is_read));
    } catch { /* silently ignore polling errors */ }
  }, []);

  useEffect(() => {
    if (!isAuthenticated || !isFieldStaffOrDispatch) return;
    axiosClient.get('/employees/me')
      .then(res => {
        const id = res.data.id as string;
        setEmployeeId(id);
        fetchNotifs(id);
        intervalRef.current = setInterval(() => fetchNotifs(id), 30_000);
      })
      .catch(() => { /* employee record not found — skip notifications */ });

    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [isAuthenticated, isFieldStaffOrDispatch, fetchNotifs]);

  const markRead = async (notifId: string) => {
    await axiosClient.patch(`/notifications/${notifId}/read`).catch(() => {});
    setNotifications(prev => prev.filter(n => n.id !== notifId));
  };

  const markAllRead = async () => {
    if (!employeeId) return;
    await axiosClient.patch(`/notifications/employee/${employeeId}/read-all`).catch(() => {});
    setNotifications([]);
  };

  return { notifications, markRead, markAllRead };
}

function NotificationDropdown({
  notifications,
  onMarkRead,
  onMarkAllRead,
  onClose,
}: {
  notifications: NavNotification[];
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
              {notifIcon(n.type)}
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// Title bar — brand + user controls
// ---------------------------------------------------------------------------

function TitleBar() {
  const { user, groups, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [bellOpen, setBellOpen] = useState(false);
  const { notifications, markRead, markAllRead } = useNotifications(isAuthenticated, groups);

  const handleSignOut = async () => {
    try {
      await signOut();
      navigate('/login');
    } catch (error) {
      console.error('Error signing out: ', error);
    }
  };

  return (
    <div className="w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
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

          {/* Username */}
          <span className="hidden md:inline-block text-xs text-muted-foreground font-medium px-2 border-l border-border">
            {user?.displayName || user?.username}
          </span>

          {/* Sign out */}
          <button
            onClick={handleSignOut}
            className="inline-flex items-center justify-center w-8 h-8 rounded-lg
                       text-muted-foreground hover:text-danger hover:bg-danger/5
                       transition-colors press"
            title="Sign out"
          >
            <LogOut className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Nav bar — links only, scrollable on overflow
// ---------------------------------------------------------------------------

const Navbar = () => {
  const { groups, isAuthenticated } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [trainerPhase, setTrainerPhase] = useState<number | null>(null);

  const isFieldStaff = groups.some(role => ['driver', 'walker', 'trainer', 'trainee'].includes(role));
  const isTrainer = groups.includes('trainer');
  const isMgmt = groups.includes('management');
  const isDispatch = groups.includes('dispatch');
  const isAdmin = groups.includes('admin');
  const canAccessFieldOps = groups.some(role => ['driver', 'walker', 'trainee'].includes(role)) || isMgmt || isDispatch || isAdmin;
  const canAccessScheduleChanges = isFieldStaff || isDispatch || isAdmin;
  const canAccessSchedule = isFieldStaff || isMgmt || isAdmin;

  useEffect(() => {
    if (!isAuthenticated || !isTrainer) return;
    axiosClient.get('/training/trainer/today')
      .then(res => setTrainerPhase(res.data?.record?.current_day_number ?? null))
      .catch(() => setTrainerPhase(null));
  }, [isAuthenticated, isTrainer]);

  const homeRoute = (() => {
    if (isAdmin)      return '/admin';
    if (isDispatch)   return '/dispatch-home';
    if (isMgmt)       return '/management';
    if (isTrainer)    return '/trainer-dashboard';
    if (groups.includes('trainee')) return '/my-training';
    return '/';
  })();

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-all duration-200 press ${
      isActive
        ? 'bg-accent text-accent-foreground shadow-sm'
        : 'text-muted-foreground hover:text-foreground hover:bg-accent/60'
    }`;

  const links = (
    <>
      <NavLink to={homeRoute} className={linkClass}><Home className="w-3.5 h-3.5" /> Home</NavLink>

      {canAccessSchedule && (
        <NavLink to="/schedule" className={linkClass}><Calendar className="w-3.5 h-3.5" /> Schedule</NavLink>
      )}
      {isFieldStaff && (
        <NavLink to="/preferences" className={linkClass}><Settings className="w-3.5 h-3.5" /> Preferences</NavLink>
      )}
      {isTrainer && (
        <NavLink to="/trainer-dashboard" className={linkClass}><ClipboardCheck className="w-3.5 h-3.5" /> Trainer Dash</NavLink>
      )}
      {isTrainer && trainerPhase === 4 && (
        <NavLink to="/phase4-observation" className={linkClass}><ClipboardCheck className="w-3.5 h-3.5" /> Phase 4</NavLink>
      )}
      {groups.includes('trainee') && (
        <NavLink to="/my-training" className={linkClass}><ClipboardCheck className="w-3.5 h-3.5" /> My Training</NavLink>
      )}
      {canAccessScheduleChanges && (
        <NavLink to="/schedule-changes" className={linkClass}><RefreshCw className="w-3.5 h-3.5" /> Schedule Changes</NavLink>
      )}
      {canAccessFieldOps && (
        <NavLink to="/field-ops" className={linkClass}><MapPin className="w-3.5 h-3.5" /> Field Ops</NavLink>
      )}
      {groups.includes('driver') && (
        <NavLink to="/anchor-points" className={linkClass}><MapPin className="w-3.5 h-3.5" /> Anchor Point</NavLink>
      )}
      <NavLink to="/incidents" className={linkClass}><AlertTriangle className="w-3.5 h-3.5" /> Incidents</NavLink>

      {(isDispatch || isAdmin) && (
        <NavLink to="/dispatch-home" className={linkClass}><ClipboardCheck className="w-3.5 h-3.5" /> Dispatch</NavLink>
      )}
      {(isDispatch || isAdmin) && (
        <NavLink to="/dispatch" className={linkClass}><ClipboardCheck className="w-3.5 h-3.5" /> Assignments</NavLink>
      )}
      {(isDispatch || isAdmin) && (
        <NavLink to="/anchor-points" className={linkClass}><MapPin className="w-3.5 h-3.5" /> Anchor Points</NavLink>
      )}

      {isMgmt && (
        <>
          <NavLink to="/assets" className={linkClass}><Users className="w-3.5 h-3.5" /> Assets</NavLink>
          <NavLink to="/trainee-management" className={linkClass}><ClipboardCheck className="w-3.5 h-3.5" /> Trainees</NavLink>
          <NavLink to="/vehicle-compliance" className={linkClass}><ShieldAlert className="w-3.5 h-3.5" /> Compliance</NavLink>
          <NavLink to="/walker-performance" className={linkClass}><Star className="w-3.5 h-3.5" /> Walkers</NavLink>
          <NavLink to="/operations-analytics" className={linkClass}><BarChart2 className="w-3.5 h-3.5" /> Analytics</NavLink>
        </>
      )}
      {isDispatch && !isAdmin && (
        <NavLink to="/operations-analytics" className={linkClass}><BarChart2 className="w-3.5 h-3.5" /> Analytics</NavLink>
      )}
      {isAdmin && (
        <>
          <NavLink to="/assets" className={linkClass}><Users className="w-3.5 h-3.5" /> Assets</NavLink>
          <NavLink to="/feedback" className={linkClass}><MessageSquare className="w-3.5 h-3.5" /> Feedback</NavLink>
          <NavLink to="/operations-analytics" className={linkClass}><BarChart2 className="w-3.5 h-3.5" /> Analytics</NavLink>
          <NavLink to="/settings" className={linkClass}><Settings className="w-3.5 h-3.5" /> Settings</NavLink>
          <NavLink to="/admin" className={linkClass}><Shield className="w-3.5 h-3.5" /> Admin</NavLink>
        </>
      )}
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
              {/* Re-render links with mobile classes */}
              <MobileLinks
                groups={groups}
                isTrainer={isTrainer}
                trainerPhase={trainerPhase}
                homeRoute={homeRoute}
                canAccessFieldOps={canAccessFieldOps}
                canAccessScheduleChanges={canAccessScheduleChanges}
                canAccessSchedule={canAccessSchedule}
                isFieldStaff={isFieldStaff}
                isMgmt={isMgmt}
                isDispatch={isDispatch}
                isAdmin={isAdmin}
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
  groups, isTrainer, trainerPhase, homeRoute,
  canAccessFieldOps, canAccessScheduleChanges, canAccessSchedule,
  isFieldStaff, isMgmt, isDispatch, isAdmin,
  onNav,
}: {
  groups: string[]; isTrainer: boolean; trainerPhase: number | null;
  homeRoute: string; canAccessFieldOps: boolean; canAccessScheduleChanges: boolean;
  canAccessSchedule: boolean; isFieldStaff: boolean; isMgmt: boolean;
  isDispatch: boolean; isAdmin: boolean; onNav: () => void;
}) {
  const cls = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
      isActive
        ? 'bg-accent text-accent-foreground shadow-sm'
        : 'text-muted-foreground hover:text-foreground hover:bg-accent/60'
    }`;

  return (
    <>
      <NavLink to={homeRoute} onClick={onNav} className={cls}><Home className="w-4 h-4" /> Home</NavLink>
      {canAccessSchedule && <NavLink to="/schedule" onClick={onNav} className={cls}><Calendar className="w-4 h-4" /> Schedule</NavLink>}
      {isFieldStaff && <NavLink to="/preferences" onClick={onNav} className={cls}><Settings className="w-4 h-4" /> Preferences</NavLink>}
      {isTrainer && <NavLink to="/trainer-dashboard" onClick={onNav} className={cls}><ClipboardCheck className="w-4 h-4" /> Trainer Dash</NavLink>}
      {isTrainer && trainerPhase === 4 && <NavLink to="/phase4-observation" onClick={onNav} className={cls}><ClipboardCheck className="w-4 h-4" /> Phase 4</NavLink>}
      {groups.includes('trainee') && <NavLink to="/my-training" onClick={onNav} className={cls}><ClipboardCheck className="w-4 h-4" /> My Training</NavLink>}
      {canAccessScheduleChanges && <NavLink to="/schedule-changes" onClick={onNav} className={cls}><RefreshCw className="w-4 h-4" /> Schedule Changes</NavLink>}
      {canAccessFieldOps && <NavLink to="/field-ops" onClick={onNav} className={cls}><MapPin className="w-4 h-4" /> Field Ops</NavLink>}
      {groups.includes('driver') && <NavLink to="/anchor-points" onClick={onNav} className={cls}><MapPin className="w-4 h-4" /> Anchor Point</NavLink>}
      <NavLink to="/incidents" onClick={onNav} className={cls}><AlertTriangle className="w-4 h-4" /> Incidents</NavLink>
      {(isDispatch || isAdmin) && <NavLink to="/dispatch-home" onClick={onNav} className={cls}><ClipboardCheck className="w-4 h-4" /> Dispatch</NavLink>}
      {(isDispatch || isAdmin) && <NavLink to="/dispatch" onClick={onNav} className={cls}><ClipboardCheck className="w-4 h-4" /> Assignments</NavLink>}
      {(isDispatch || isAdmin) && <NavLink to="/anchor-points" onClick={onNav} className={cls}><MapPin className="w-4 h-4" /> Anchor Points</NavLink>}
      {isMgmt && <>
        <NavLink to="/assets" onClick={onNav} className={cls}><Users className="w-4 h-4" /> Assets</NavLink>
        <NavLink to="/trainee-management" onClick={onNav} className={cls}><ClipboardCheck className="w-4 h-4" /> Trainees</NavLink>
        <NavLink to="/vehicle-compliance" onClick={onNav} className={cls}><ShieldAlert className="w-4 h-4" /> Compliance</NavLink>
        <NavLink to="/walker-performance" onClick={onNav} className={cls}><Star className="w-4 h-4" /> Walkers</NavLink>
        <NavLink to="/operations-analytics" onClick={onNav} className={cls}><BarChart2 className="w-4 h-4" /> Analytics</NavLink>
      </>}
      {isDispatch && !isAdmin && <NavLink to="/operations-analytics" onClick={onNav} className={cls}><BarChart2 className="w-4 h-4" /> Analytics</NavLink>}
      {isAdmin && <>
        <NavLink to="/assets" onClick={onNav} className={cls}><Users className="w-4 h-4" /> Assets</NavLink>
        <NavLink to="/feedback" onClick={onNav} className={cls}><MessageSquare className="w-4 h-4" /> Feedback</NavLink>
        <NavLink to="/operations-analytics" onClick={onNav} className={cls}><BarChart2 className="w-4 h-4" /> Analytics</NavLink>
        <NavLink to="/settings" onClick={onNav} className={cls}><Settings className="w-4 h-4" /> Settings</NavLink>
        <NavLink to="/admin" onClick={onNav} className={cls}><Shield className="w-4 h-4" /> Admin</NavLink>
      </>}
    </>
  );
}

export default Navbar;
