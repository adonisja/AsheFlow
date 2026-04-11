import React, { useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { signOut } from 'aws-amplify/auth';
import { useAuth } from '../../contexts/AuthContext';
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
} from 'lucide-react';

const Navbar = () => {
  const { user, groups } = useAuth();
  const navigate = useNavigate();
  const [isOpen, setIsOpen] = useState(false);

  const isFieldStaff = groups.some(role => ['driver', 'walker', 'trainer', 'trainee'].includes(role));
  const canAccessFieldOps = groups.includes('driver') || groups.includes('admin');
  const canAccessScheduleChanges = isFieldStaff || groups.some(role => ['dispatch', 'admin'].includes(role));
  const isDispatchOrAdmin = groups.some(role => ['admin', 'dispatch'].includes(role));
  const isAdminOrMgmt = groups.some(role => ['admin', 'management'].includes(role));

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
        ? 'bg-primary text-primary-foreground' 
        : 'text-muted-foreground hover:text-foreground hover:bg-accent'
    }`;

  const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all duration-200 ${
      isActive 
        ? 'bg-primary text-primary-foreground' 
        : 'text-muted-foreground hover:text-foreground hover:bg-accent'
    }`;

  return (
    <nav className="sticky top-0 z-50 bg-card/80 backdrop-blur-xl border-b border-border">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-2.5 text-foreground font-bold text-lg tracking-tight">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary">
                <Truck className="h-4 w-4 text-primary-foreground" />
              </div>
              AsheFlow
            </div>
            
            {/* Desktop Navigation */}
            <div className="hidden md:flex items-center gap-1">
              <NavLink to="/" className={navLinkClass}>
                <Home className="w-4 h-4" /> Home
              </NavLink>
              {isFieldStaff && (
                <NavLink to="/schedule" className={navLinkClass}>
                  <Calendar className="w-4 h-4" /> Schedule
                </NavLink>
              )}
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
            <span className="text-sm text-muted-foreground">
              {user?.displayName || user?.username}
            </span>
            <button
              onClick={handleSignOut}
              className="btn-ghost text-muted-foreground"
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
        <div className="md:hidden animate-slide-up border-t border-border bg-card">
          <div className="px-3 py-4 space-y-1">
            <NavLink to="/" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
              <Home className="w-5 h-5" /> Home
            </NavLink>
            {isFieldStaff && (
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
              </>
            )}
            {groups.includes('admin') && (
              <NavLink to="/admin" onClick={() => setIsOpen(false)} className={mobileNavLinkClass}>
                <Shield className="w-5 h-5" /> Admin
              </NavLink>
            )}
          </div>
          <div className="px-3 py-4 border-t border-border">
            <div className="px-4 mb-3 text-sm text-muted-foreground">
              {user?.displayName || user?.username}
            </div>
            <button
              onClick={handleSignOut}
              className="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent transition-all"
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
