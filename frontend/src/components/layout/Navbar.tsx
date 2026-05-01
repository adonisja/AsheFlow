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

// Dropdown shown when bell is clicked
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

const Navbar = () => {
  const { user, groups, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const { notifications, markRead, markAllRead } = useNotifications(isAuthenticated, groups);

  const isFieldStaff = groups.some(role => ['driver', 'walker', 'trainer', 'trainee'].includes(role));
  const isMgmt = groups.includes('management');
  const isAdmin = groups.includes('admin');
  const canAccessFieldOps = isFieldStaff || isAdmin;
  const canAccessScheduleChanges = isFieldStaff || groups.includes('dispatch') || isAdmin;
  const canAccessSchedule = isFieldStaff || isMgmt || isAdmin;

  const homeRoute = (() => {
    if (groups.includes('admin'))       return '/admin';
    if (groups.includes('dispatch'))    return '/dispatch-home';
    if (groups.includes('management'))  return '/management';
    if (groups.includes('trainer'))     return '/trainer-dashboard';
    if (groups.includes('trainee'))     return '/my-training';
    return '/';
  })();

  const handleSignOut = async () => {
    try {
      await signOut();
      navigate('/login');
    } catch (error) {
      console.error('Error signing out: ', error);
    }
  };

  const navLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200 press ${
      isActive
        ? 'bg-accent text-accent-foreground shadow-sm'
        : 'text-muted-foreground hover:text-foreground hover:bg-accent/60'
    }`;

  const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
      isActive
        ? 'bg-accent text-accent-foreground shadow-sm'
        : 'text-muted-foreground hover:text-foreground hover:bg-accent/60'
    }`;

  return (
    <nav className="sticky top-0 z-40 glass border-x-0 border-t-0 border-b border-border/60 rounded-none">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-2.5 font-bold text-lg tracking-tight">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg gradient-primary shadow-glow-primary">
                <Truck className="h-4 w-4 text-primary-foreground" />
              </div>
              <span className="font-display gradient-text-brand">AsheFlow</span>
            </div>

            {/* Desktop Navigation */}
            <div className="hidden md:flex items-center gap-1">
              <NavLink to={homeRoute} className={navLinkClass}>
                <Home className="w-4 h-4" /> Home
              </NavLink>
              {canAccessSchedule && (
                <NavLink to="/schedule" className={navLinkClass}>
                  <Calendar className="w-4 h-4" /> Schedule
                </NavLink>
              )}
              {/* Field staff only — admin has no employee record */}
              {isFieldStaff && (
                <NavLink to="/preferences" className={navLinkClass}>
                  <Settings className="w-4 h-4" /> Preferences
                </NavLink>
              )}
              {groups.includes('trainer') && (
                <NavLink to="/trainer-dashboard" className={navLinkClass}>
                  <ClipboardCheck className="w-4 h-4" /> Trainer Dash
                </NavLink>
              )}
              {groups.includes('trainee') && (
                <NavLink to="/my-training" className={navLinkClass}>
                  <ClipboardCheck className="w-4 h-4" /> My Training
                </NavLink>
              )}
              {canAccessScheduleChanges && (
                <NavLink to="/schedule-changes" className={navLinkClass}>
                  <RefreshCw className="w-4 h-4" /> Schedule Changes
                </NavLink>
              )}
              {/* Field ops: field staff only — admin uses ⌘K */}
              {isFieldStaff && (
                <NavLink to="/field-ops" className={navLinkClass}>
                  <MapPin className="w-4 h-4" /> Field Ops
                </NavLink>
              )}
              {groups.includes('driver') && (
                <NavLink to="/anchor-points" className={navLinkClass}>
                  <MapPin className="w-4 h-4" /> Anchor Point
                </NavLink>
              )}
              <NavLink to="/incidents" className={navLinkClass}>
                <AlertTriangle className="w-4 h-4" /> Incidents
              </NavLink>
              {(groups.includes('dispatch') || isAdmin) && (
                <NavLink to="/dispatch" className={navLinkClass}>
                  <ClipboardCheck className="w-4 h-4" /> Assignments
                </NavLink>
              )}
              {(groups.includes('dispatch') || isAdmin) && (
                <NavLink to="/anchor-points" className={navLinkClass}>
                  <MapPin className="w-4 h-4" /> Anchor Points
                </NavLink>
              )}
              {/* Management tools: mgmt sees all four; admin only sees Assets */}
              {isMgmt && (
                <>
                  <NavLink to="/assets" className={navLinkClass}>
                    <Users className="w-4 h-4" /> Assets
                  </NavLink>
                  <NavLink to="/trainee-management" className={navLinkClass}>
                    <ClipboardCheck className="w-4 h-4" /> Trainees
                  </NavLink>
                  <NavLink to="/vehicle-compliance" className={navLinkClass}>
                    <ShieldAlert className="w-4 h-4" /> Compliance
                  </NavLink>
                  <NavLink to="/walker-performance" className={navLinkClass}>
                    <Star className="w-4 h-4" /> Walkers
                  </NavLink>
                  <NavLink to="/operations-analytics" className={navLinkClass}>
                    <BarChart2 className="w-4 h-4" /> Analytics
                  </NavLink>
                </>
              )}
              {(groups.includes('dispatch') && !isAdmin) && (
                <NavLink to="/operations-analytics" className={navLinkClass}>
                  <BarChart2 className="w-4 h-4" /> Analytics
                </NavLink>
              )}
              {isAdmin && (
                <>
                  <NavLink to="/assets" className={navLinkClass}>
                    <Users className="w-4 h-4" /> Assets
                  </NavLink>
                  <NavLink to="/feedback" className={navLinkClass}>
                    <MessageSquare className="w-4 h-4" /> Feedback
                  </NavLink>
                  <NavLink to="/operations-analytics" className={navLinkClass}>
                    <BarChart2 className="w-4 h-4" /> Analytics
                  </NavLink>
                  <NavLink to="/admin" className={navLinkClass}>
                    <Shield className="w-4 h-4" /> Admin
                  </NavLink>
                </>
              )}
            </div>
          </div>

          {/* Desktop right cluster */}
          <div className="hidden md:flex items-center gap-2">
            {/* Command palette trigger */}
            <button
              onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', metaKey: true }))}
              className="hidden lg:inline-flex items-center gap-2 px-3 h-9 rounded-xl border border-border
                         bg-surface text-muted-foreground hover:text-foreground hover:border-border-strong
                         transition-colors press text-xs"
              title="Open command palette"
            >
              <Search className="h-3.5 w-3.5" />
              <span>Search</span>
              <span className="ml-2 flex items-center gap-0.5">
                <span className="kbd">⌘</span>
                <span className="kbd">K</span>
              </span>
            </button>

            <ThemeToggle />

            {/* Notification Bell */}
            <div className="relative">
              <button
                onClick={() => setBellOpen(o => !o)}
                className="relative inline-flex items-center justify-center w-9 h-9 rounded-xl
                           border border-border bg-surface text-muted-foreground
                           hover:text-foreground hover:border-border-strong transition-colors press"
                title="Notifications"
              >
                <Bell className="h-4 w-4" />
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

            <span className="hidden xl:inline-block text-sm text-muted-foreground font-medium pl-3 ml-1 border-l border-border">
              {user?.displayName || user?.username}
            </span>

            <button
              onClick={handleSignOut}
              className="btn-ghost text-muted-foreground hover:text-danger"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>

          {/* Mobile menu button */}
          <button
            onClick={() => setIsOpen(!isOpen)}
            className="md:hidden btn-ghost"
          >
            <span className="sr-only">Open main menu</span>
            {isOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {isOpen && (
        <div className="md:hidden animate-slide-up border-t border-border/50 bg-card">
          <div className="px-3 py-4 space-y-1">
            <NavLink to={homeRoute} onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
              <Home className="w-5 h-5" /> Home
            </NavLink>
            {canAccessSchedule && (
              <NavLink to="/schedule" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <Calendar className="w-5 h-5" /> Schedule
              </NavLink>
            )}
            {isFieldStaff && (
              <NavLink to="/preferences" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <Settings className="w-5 h-5" /> Preferences
              </NavLink>
            )}
            {groups.includes('trainee') && (
              <NavLink to="/my-training" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <ClipboardCheck className="w-5 h-5" /> My Training
              </NavLink>
            )}
            {groups.includes('trainer') && (
              <NavLink to="/trainer-dashboard" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <ClipboardCheck className="w-5 h-5" /> Trainer Dash
              </NavLink>
            )}
            {canAccessScheduleChanges && (
              <NavLink to="/schedule-changes" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <RefreshCw className="w-5 h-5" /> Schedule Changes
              </NavLink>
            )}
            {isFieldStaff && (
              <NavLink to="/field-ops" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <MapPin className="w-5 h-5" /> Field Ops
              </NavLink>
            )}
            {groups.includes('driver') && (
              <NavLink to="/anchor-points" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <MapPin className="w-5 h-5" /> Anchor Point
              </NavLink>
            )}
            <NavLink to="/incidents" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
              <AlertTriangle className="w-5 h-5" /> Incidents
            </NavLink>
            {(groups.includes('dispatch') || isAdmin) && (
              <NavLink to="/dispatch" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <ClipboardCheck className="w-5 h-5" /> Assignments
              </NavLink>
            )}
            {(groups.includes('dispatch') || isAdmin) && (
              <NavLink to="/anchor-points" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <MapPin className="w-5 h-5" /> Anchor Points
              </NavLink>
            )}
            {isMgmt && (
              <>
                <NavLink to="/assets" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                  <Users className="w-5 h-5" /> Assets
                </NavLink>
                <NavLink to="/trainee-management" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                  <ClipboardCheck className="w-5 h-5" /> Trainees
                </NavLink>
                <NavLink to="/vehicle-compliance" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                  <ShieldAlert className="w-5 h-5" /> Compliance
                </NavLink>
                <NavLink to="/walker-performance" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                  <Star className="w-5 h-5" /> Walkers
                </NavLink>
                <NavLink to="/operations-analytics" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                  <BarChart2 className="w-5 h-5" /> Analytics
                </NavLink>
              </>
            )}
            {(groups.includes('dispatch') && !isAdmin) && (
              <NavLink to="/operations-analytics" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <BarChart2 className="w-5 h-5" /> Analytics
              </NavLink>
            )}
            {isAdmin && (
              <>
                <NavLink to="/assets" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                  <Users className="w-5 h-5" /> Assets
                </NavLink>
                <NavLink to="/feedback" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                  <MessageSquare className="w-5 h-5" /> Feedback
                </NavLink>
                <NavLink to="/operations-analytics" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                  <BarChart2 className="w-5 h-5" /> Analytics
                </NavLink>
                <NavLink to="/admin" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                  <Shield className="w-5 h-5" /> Admin
                </NavLink>
              </>
            )}
          </div>
          <div className="px-3 py-4 border-t border-border/50">
            <div className="px-4 mb-3 text-sm text-muted-foreground font-medium">
              {user?.displayName || user?.username}
            </div>
            <button
              onClick={handleSignOut}
              className="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-sm font-medium text-muted-foreground hover:text-danger hover:bg-danger/5 transition-all"
            >
              <LogOut className="w-5 h-5" /> Sign out
            </button>
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;
