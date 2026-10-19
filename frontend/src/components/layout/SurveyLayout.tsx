/**
 * ADR-543 D1 — the survey register's app bar.
 *
 * The survey pages stay OUTSIDE the tenant and super-admin layouts (ADR-504):
 * a contributor has no Employee row, and the page is used on a phone on a
 * sidewalk. But "outside every layout" had become "no way out": a super admin
 * who opened it could not get back to platform admin, and nobody could see how
 * to sign out. This bar adds exactly those two exits and nothing that needs an
 * Employee row.
 */
import { Link, Outlet, useNavigate } from 'react-router-dom';
import { signOut } from 'aws-amplify/auth';
import { ArrowLeft, LogOut, MapPinned } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import MfaNudgeBanner from '../MfaNudgeBanner';

export default function SurveyLayout() {
  const navigate = useNavigate();
  const { groups } = useAuth();
  const isSuperAdmin = groups.includes('super_admin');

  const handleSignOut = async () => {
    try { await signOut(); } finally { navigate('/login'); }
  };

  return (
    <div className="min-h-screen bg-background">
      <header
        className="sticky top-0 z-40 border-b border-border/60 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/70"
        style={{ paddingTop: 'env(safe-area-inset-top, 0px)' }}
      >
        <div className="layout-shell h-14 flex items-center justify-between gap-3">
          <Link to="/survey" className="flex items-center gap-2 min-w-0 font-bold tracking-tight">
            <span className="flex items-center justify-center w-8 h-8 rounded-lg bg-brand/15 border border-brand/30 shrink-0">
              <MapPinned className="h-4 w-4 text-brand" aria-hidden="true" />
            </span>
            <span className="font-display text-foreground">AsheFlow</span>
            <span className="hidden sm:inline text-xs font-normal text-muted-foreground border border-border rounded-md px-1.5 py-0.5">
              Survey register
            </span>
          </Link>

          <nav className="flex items-center gap-1" aria-label="Leave the survey register">
            {/* A super admin arrived from platform admin and needs the way back.
                A contributor has nowhere else in the app, so they get sign-out only. */}
            {isSuperAdmin && (
              <Link
                to="/superadmin/companies"
                className="btn-ghost min-h-11 px-3 text-sm flex items-center gap-1.5"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                <span>Platform admin</span>
              </Link>
            )}
            <button
              type="button"
              onClick={handleSignOut}
              className="btn-ghost min-h-11 px-3 text-sm flex items-center gap-1.5"
              aria-label="Sign out"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              <span className="hidden sm:inline">Sign out</span>
            </button>
          </nav>
        </div>
      </header>
      {/* ADR-396: every shell mounts it. A super admin is privileged with no
          grace period; it renders nothing for anyone with nothing owed. */}
      <div className="layout-shell pt-3">
        <MfaNudgeBanner />
      </div>
      <Outlet />
    </div>
  );
}
