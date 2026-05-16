import React from 'react';
import { Outlet, NavLink, useNavigate } from 'react-router-dom';
import { Shield, Building2, LogOut, UserCircle2 } from 'lucide-react';
import { signOut } from 'aws-amplify/auth';
import ThemeToggle from '../ui/ThemeToggle';

const NAV = [
  { to: '/superadmin/companies', label: 'Companies',  icon: Building2  },
  { to: '/superadmin/account',   label: 'My Account', icon: UserCircle2 },
];

export default function SuperAdminLayout() {
  const navigate = useNavigate();

  return (
    <div className="relative min-h-screen bg-background flex flex-col">
      {/* Ambient backdrop — distinct violet tint to visually separate from company UI */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div
          className="absolute -top-32 -left-32 w-[640px] h-[640px] rounded-full opacity-[0.15] dark:opacity-[0.20]"
          style={{ background: 'radial-gradient(circle, hsl(var(--violet) / 0.6), transparent 70%)' }}
        />
        <div
          className="absolute top-[40%] -right-40 w-[520px] h-[520px] rounded-full opacity-[0.10] dark:opacity-[0.18]"
          style={{ background: 'radial-gradient(circle, hsl(var(--primary) / 0.5), transparent 70%)' }}
        />
      </div>

      {/* Top bar */}
      <header className="sticky top-0 z-40 border-b border-border/60 bg-background/80 backdrop-blur-md">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center gap-4">
          {/* Brand */}
          <div className="flex items-center gap-2 text-violet-500 font-semibold text-sm select-none">
            <Shield className="w-4 h-4" />
            <span>AsheFlow</span>
            <span className="text-muted-foreground font-normal">/ Super Admin</span>
          </div>

          {/* Nav links */}
          <nav className="flex items-center gap-1 ml-4">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-violet-500/10 text-violet-500'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent'
                  }`
                }
              >
                <Icon className="w-3.5 h-3.5" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <button
              onClick={async () => { try { await signOut(); } finally { navigate('/login'); } }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-muted-foreground hover:text-danger hover:bg-danger/5 transition-colors"
            >
              <LogOut className="w-3.5 h-3.5" />
              Sign out
            </button>
          </div>
        </div>
      </header>

      {/* Page content */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Outlet />
      </main>
    </div>
  );
}
