import { useEffect, useRef, useState } from 'react';
import { Outlet, NavLink, Link, useNavigate } from 'react-router-dom';
import {
  Shield, Building2, LogOut, UserCircle2, ShieldAlert, ShieldCheck,
  ClipboardList, Menu, X,
} from 'lucide-react';
import { signOut } from 'aws-amplify/auth';
import ThemeToggle from '../ui/ThemeToggle';
import Avatar from '../ui/Avatar';
import MfaNudgeBanner from '../MfaNudgeBanner';
import { useAuth } from '../../contexts/AuthContext';

const NAV = [
  { to: '/superadmin/companies', label: 'Companies',  icon: Building2  },
  // ADR-340 — the heartbeat (ADR-337) detects a revoked credential within ten
  // minutes and wrote it to a board nobody could reach. This is the reader.
  { to: '/superadmin/alerts',    label: 'Alerts',     icon: ShieldAlert },
  // ADR-394 — creating a second super admin and resetting a locked-out account
  // both existed only as AWS CLI commands in a runbook: unaudited, untested and
  // unavailable to anyone without AWS credentials.
  { to: '/superadmin/staff',     label: 'Staff',      icon: ShieldCheck },
  // ADR-415 — the public collection page submits into a quarantine table that
  // had no reader. Super admin, not platform staff: the rows are customer
  // delivery addresses, and ADR-343 D4 keeps PII off every platform_support path.
  { to: '/superadmin/collection', label: 'Collected', icon: ClipboardList },
];

/** Brand + identity row.
 *
 *  Mirrors the tenant Navbar's TitleBar deliberately: same two-tier shape, same
 *  32px avatar and dropdown, same utility cluster. The SKIN differs — violet
 *  rather than the brand gradient — because super admin spans every tenant and
 *  should never be mistaken for one of them. Structure is shared so it does not
 *  read as a lesser surface; colour is not, so it does not read as the same one.
 */
function TitleBar() {
  const navigate = useNavigate();
  const { user, groups } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMenuOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [menuOpen]);

  const handleSignOut = async () => {
    try { await signOut(); } finally { navigate('/login'); }
  };

  return (
    <div className="relative z-10 w-full border-b border-border/40 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-12 flex items-center justify-between gap-4">
        {/* Brand — the tenant navbar's tile treatment, in violet */}
        <div className="flex items-center gap-2 font-bold text-base tracking-tight shrink-0">
          <div className="flex items-center justify-center w-7 h-7 rounded-lg bg-brand/15 border border-brand/30">
            <Shield className="h-3.5 w-3.5 text-brand" />
          </div>
          <span className="font-display text-foreground">AsheFlow</span>
          <span className="hidden sm:inline text-xs font-normal text-brand border border-brand/30 bg-brand/10 rounded-md px-1.5 py-0.5">
            Super Admin
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <ThemeToggle />

          {/* Identity. The tenant navbar has shown who you are since ADR-341;
              this surface can purge a tenant and showed nothing at all. */}
          <div className="relative" ref={menuRef}>
            <button
              onClick={() => setMenuOpen(o => !o)}
              className="flex items-center rounded-full focus:outline-none focus:ring-2 focus:ring-brand/40 press"
              title="Account"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
            >
              <Avatar size={32} />
            </button>

            {menuOpen && (
              <div className="absolute right-0 top-10 z-50 w-56 rounded-xl border border-border bg-card shadow-lg py-1 animate-slide-up">
                <div className="px-4 py-3 border-b border-border flex items-center gap-3">
                  <Avatar size={36} />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-foreground truncate">
                      {user?.displayName || user?.username}
                    </p>
                    <p className="text-xs text-muted-foreground capitalize">
                      {groups[0]?.replace('_', ' ') ?? 'super admin'}
                    </p>
                  </div>
                </div>
                <div className="py-1">
                  <Link
                    to="/superadmin/account"
                    onClick={() => setMenuOpen(false)}
                    className="flex items-center gap-2.5 px-4 py-2 text-sm text-foreground hover:bg-accent transition-colors"
                  >
                    <UserCircle2 className="w-4 h-4 text-muted-foreground" />
                    My Account
                  </Link>
                  <button
                    onClick={() => { setMenuOpen(false); handleSignOut(); }}
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

export default function SuperAdminLayout() {
  const [mobileOpen, setMobileOpen] = useState(false);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-all duration-200 press ${
      isActive
        ? 'bg-brand/10 text-brand'
        : 'text-muted-foreground hover:text-foreground hover:bg-accent'
    }`;

  return (
    <div className="relative min-h-screen bg-background flex flex-col">
      {/* Ambient backdrop — the brand violet, separating this surface from any
          tenant's UI. It referenced `--violet`, which is not a token and never
          has been, so this gradient has been rendering nothing. */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
        <div
          className="absolute -top-32 -left-32 w-[640px] h-[640px] rounded-full opacity-[0.15] dark:opacity-[0.20]"
          style={{ background: 'radial-gradient(circle, hsl(var(--brand) / 0.6), transparent 70%)' }}
        />
        <div
          className="absolute top-[40%] -right-40 w-[520px] h-[520px] rounded-full opacity-[0.10] dark:opacity-[0.18]"
          style={{ background: 'radial-gradient(circle, hsl(var(--primary) / 0.5), transparent 70%)' }}
        />
      </div>

      <header className="sticky top-0 z-40">
        <TitleBar />

        {/* Nav strip — its own row, as in the tenant navbar. Sharing one row
            with the brand is what made this feel cramped: the links had to
            compete for width with a wordmark that never changes. */}
        <nav className="glass border-x-0 border-t-0 border-b border-border/60 rounded-none">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex items-center justify-between h-10">
              <div className="hidden md:flex items-center min-w-0 flex-1">
                <div className="flex items-center gap-0.5 overflow-x-auto scrollbar-none pr-2">
                  {NAV.map(({ to, label, icon: Icon }) => (
                    <NavLink key={to} to={to} className={linkClass}>
                      <Icon className="w-3.5 h-3.5" />
                      {label}
                    </NavLink>
                  ))}
                </div>
              </div>

              {/* Mobile: there was no treatment at all before — the links
                  simply overflowed the row. */}
              <button
                onClick={() => setMobileOpen(o => !o)}
                className="md:hidden btn-ghost p-1.5"
                aria-label="Toggle menu"
                aria-expanded={mobileOpen}
              >
                {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {mobileOpen && (
            <div className="md:hidden border-t border-border/40 px-4 py-2 space-y-0.5">
              {NAV.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  onClick={() => setMobileOpen(false)}
                  className={linkClass}
                >
                  <Icon className="w-4 h-4" />
                  {label}
                </NavLink>
              ))}
            </div>
          )}
        </nav>
      </header>

      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* ADR-396 — this shell deliberately omits the tenant-scoped pieces of
            the main Layout (NotificationBanner, CommandPalette, FeedbackModal),
            all of which resolve the caller through an Employee row a super admin
            does not have. The MFA banner is NOT one of those: it reads only
            `mfaStatus` from AuthContext and applies to every human with an
            account.

            It matters most here. ADR-377 puts super_admin on the PRIVILEGED tier
            with no grace period, so this is the one role that must enrol before
            first use -- and it was the one role never told to. */}
        <MfaNudgeBanner />
        <Outlet />
      </main>
    </div>
  );
}
