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
  Star,
  Bell,
  CheckCircle2,
  XCircle,
  Info,
} from 'lucide-react';

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

function useNotifications(isAuthenticated: boolean) {
  const [employeeId, setEmployeeId] = useState<string | null>(null);
  const [notifications, setNotifications] = useState<NavNotification[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchNotifs = useCallback(async (empId: string) => {
    try {
      const res = await axiosClient.get<NavNotification[]>(`/notifications/${empId}`, { params: { limit: 20 } });
      setNotifications(res.data.filter(n => !n.is_read));
    } catch { /* silently ignore polling errors */ }
  }, []);

  useEffect(() => {
    if (!isAuthenticated) return;
    axiosClient.get('/employees/me')
      .then(res => {
        const id = res.data.id as string;
        setEmployeeId(id);
        fetchNotifs(id);
        intervalRef.current = setInterval(() => fetchNotifs(id), 30_000);
      })
      .catch(() => { /* not yet resolved — ignore */ });

    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [isAuthenticated, fetchNotifs]);

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
  const { notifications, markRead, markAllRead } = useNotifications(isAuthenticated);

  const isFieldStaff = groups.some(role => ['driver', 'walker', 'trainer', 'trainee'].includes(role));
  // field-ops: drivers use check-in/departure/inspections; walkers/trainers/trainees can submit ratings
  const canAccessFieldOps = isFieldStaff || groups.includes('admin');
  // schedule-changes: field staff + dispatch + admin only; management reviews via /schedule
  const canAccessScheduleChanges = isFieldStaff || groups.includes('dispatch') || groups.includes('admin');
  const canAccessSchedule = isFieldStaff || groups.includes('management') || groups.includes('admin');
  const isDispatchOrAdmin = groups.some(role => ['admin', 'dispatch'].includes(role));
  const isAdminOrMgmt = groups.some(role => ['admin', 'management'].includes(role));

  const homeRoute = (() => {
    if (groups.includes('admin'))       return '/admin';
    if (groups.includes('dispatch'))    return '/dispatch';
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
    `flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
      isActive 
        ? 'gradient-primary text-primary-foreground shadow-sm shadow-primary/25' 
        : 'text-muted-foreground hover:text-accent-foreground hover:bg-accent'
    }`;

  const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
      isActive 
        ? 'gradient-primary text-primary-foreground shadow-sm shadow-primary/25' 
        : 'text-muted-foreground hover:text-accent-foreground hover:bg-accent'
    }`;

  return (
    <nav className="sticky top-0 z-50 bg-card/80 backdrop-blur-xl border-b border-border/50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-2.5 font-bold text-lg tracking-tight">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg gradient-primary shadow-sm shadow-primary/30">
                <Truck className="h-4 w-4 text-primary-foreground" />
              </div>
              <span className="bg-clip-text text-transparent bg-gradient-to-r from-primary to-violet">AsheFlow</span>
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
              {(isFieldStaff || groups.includes('admin')) && (
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
              {canAccessFieldOps && (
                <NavLink to="/field-ops" className={navLinkClass}>
                  <MapPin className="w-4 h-4" /> Field Ops
                </NavLink>
              )}
              <NavLink to="/incidents" className={navLinkClass}>
                <AlertTriangle className="w-4 h-4" /> Incidents
              </NavLink>
              {isDispatchOrAdmin && (
                <NavLink to="/dispatch" className={navLinkClass}>
                  <ClipboardCheck className="w-4 h-4" /> Dispatch
                </NavLink>
              )}
              {isAdminOrMgmt && (
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
                </>
              )}
              {groups.includes('admin') && (
                <NavLink to="/admin" className={navLinkClass}>
                  <Shield className="w-4 h-4" /> Admin
                </NavLink>
              )}
            </div>
          </div>

          {/* User Info & Logout (Desktop) */}
          <div className="hidden md:flex items-center gap-4">
            <span className="text-sm text-muted-foreground font-medium">
              {user?.displayName || user?.username}
            </span>

            {/* Notification Bell */}
            <div className="relative">
              <button
                onClick={() => setBellOpen(o => !o)}
                className="btn-ghost text-muted-foreground hover:text-foreground relative"
                title="Notifications"
              >
                <Bell className="h-4 w-4" />
                {notifications.length > 0 && (
                  <span className="absolute -top-1 -right-1 flex items-center justify-center w-4 h-4 rounded-full bg-danger text-primary-foreground text-[10px] font-bold leading-none">
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

            <button
              onClick={handleSignOut}
              className="btn-ghost text-muted-foreground hover:text-danger"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
              <span>Sign out</span>
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
            {(isFieldStaff || groups.includes('admin')) && (
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
            {canAccessFieldOps && (
              <NavLink to="/field-ops" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <MapPin className="w-5 h-5" /> Field Ops
              </NavLink>
            )}
            <NavLink to="/incidents" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
              <AlertTriangle className="w-5 h-5" /> Incidents
            </NavLink>
            {isDispatchOrAdmin && (
              <NavLink to="/dispatch" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <ClipboardCheck className="w-5 h-5" /> Dispatch
              </NavLink>
            )}
            {isAdminOrMgmt && (
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
              </>
            )}
            {groups.includes('admin') && (
              <NavLink to="/admin" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <Shield className="w-5 h-5" /> Admin
              </NavLink>
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
