import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import Login from './components/auth/Login';
import Register from './pages/Register';
import Layout from './components/layout/Layout';
import Preferences from './pages/Preferences';
import Schedule from './pages/Schedule';
import DispatchDashboard from './pages/DispatchDashboard';
import DispatchHome from './pages/DispatchHome';
import TrainerDashboard from './pages/TrainerDashboard';
import TraineeManagement from './pages/TraineeManagement';
import TraineeDashboard from './pages/TraineeDashboard';
import FieldOps from './pages/FieldOps';
import Incidents from './pages/Incidents';
import AdminDashboard from './pages/AdminDashboard';
import FeedbackAdmin from './pages/FeedbackAdmin';
import ScheduleChanges from './pages/ScheduleChanges';
import Assets from './pages/Assets';
import VehicleCompliance from './pages/VehicleCompliance';
import WalkerPerformance from './pages/WalkerPerformance';
import TrainerMarks from './pages/TrainerMarks';
import Phase4Observation from './pages/Phase4Observation';
import TrainingCurriculum from './pages/TrainingCurriculum';
import GraduationQuiz from './pages/GraduationQuiz';
import GearRequest from './pages/GearRequest';
import GraduationQuizReview from './pages/GraduationQuizReview';
import OperationsAnalytics from './pages/OperationsAnalytics';
import DriverSurveys from './pages/DriverSurveys';
import AnchorPoints from './pages/AnchorPoints';
import CrewStatus from './pages/CrewStatus';
import CaptainDashboard from './pages/CaptainDashboard';
import ScorecardEntry from './pages/ScorecardEntry';
import CompanySettings from './pages/CompanySettings';
import Account from './pages/Account';
// TEMPORARY design-review route for the ADR-271 drill-down mock. Remove with
// the mock once the wired version lands.
import AuditLog from './pages/AuditLog';
import SortPage from './pages/Sort';
import SortMetricsPage from './pages/SortMetrics';
import { routeRoles } from './config/navConfig';
import PrintLoadSheets from './pages/PrintLoadSheets';
import ReturnsManifestPrint from './pages/ReturnsManifestPrint';
import WalkerSortMonitor from './pages/WalkerSort';
import NotificationsHistory from './pages/NotificationsHistory';
import MyRoute from './pages/MyRoute';
import BuildingProfilesPage from './pages/BuildingProfiles';
import TruckBuildingsPage from './pages/TruckBuildings';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { NotificationProvider } from './contexts/NotificationContext';
import SuperAdminLayout from './components/layout/SuperAdminLayout';
import Companies from './pages/superadmin/Companies';
import CompanyDetail from './pages/superadmin/CompanyDetail';
import PlatformAlerts from './pages/superadmin/PlatformAlerts';
import { useParams } from 'react-router-dom';
function CompanyDetailWithKey() {
  const { companyId } = useParams<{ companyId: string }>();
  return <CompanyDetail key={companyId} />;
}
import DispatchView from './components/dashboard/DispatchView';
import ManagementView from './components/dashboard/ManagementView';
import WorkerView from './components/dashboard/WorkerView';
import { Users, Calendar } from 'lucide-react';
import CompanyStandingCard from './components/CompanyStandingCard';
import ScorecardAppeals from './pages/ScorecardAppeals';
import ScorecardRoster from './pages/ScorecardRoster';
import Scorecards from './pages/Scorecards';
import FieldPackages from './pages/FieldPackages';


const ProtectedRoute = ({ children, allowedRoles = [] }: { children: React.ReactNode, allowedRoles?: string[] }) => {
  const { isAuthenticated, isLoading, groups, isConfigured } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-muted-foreground">Loading...</span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) return <Navigate to="/login" />;

  // Unconfigured admin: redirect to setup for every route except /setup itself
  if (groups.includes('admin') && !isConfigured && location.pathname !== '/setup') {
    return <Navigate to="/setup" replace />;
  }

  if (allowedRoles.length > 0) {
    const hasRole = groups.some(role => allowedRoles.includes(role));
    if (!hasRole) {
      return (
        <div className="flex h-[60vh] items-center justify-center">
          <div className="card text-center max-w-md">
            <p className="text-danger font-medium">Access Denied</p>
            <p className="text-subtle mt-2">You need one of these roles: {allowedRoles.join(', ')}</p>
          </div>
        </div>
      );
    }
  }

  return <>{children}</>;
};

function RoleRedirect() {
  const { groups, isConfigured, isLoading } = useAuth();
  if (isLoading) return null;
  if (groups.includes('super_admin')) return <Navigate to="/superadmin/companies" replace />;
  if (groups.includes('admin'))       return <Navigate to={isConfigured ? '/admin' : '/setup'} replace />;
  if (groups.includes('dispatch'))    return <Navigate to="/dispatch-home" replace />;
  if (groups.includes('management'))  return <Navigate to="/management" replace />;
  if (groups.includes('captain'))     return <Navigate to="/captain-dashboard" replace />;
  if (groups.includes('trainer'))     return <Navigate to="/trainer-dashboard" replace />;
  if (groups.includes('trainee'))     return <Navigate to="/my-training" replace />;
  return <Dashboard />;
}

type DashView = 'dispatch' | 'management' | 'worker';

function Dashboard() {
  const { user, groups } = useAuth();

  const isDispatch   = groups.includes('dispatch');
  const isManagement = groups.includes('management');
  const isAdmin      = groups.includes('admin');

  // Determine default view and which tabs admin can switch between
  const defaultView = (): DashView => {
    if (isDispatch) return 'dispatch';
    if (isManagement) return 'management';
    return 'worker';
  };

  const [activeView, setActiveView] = useState<DashView>(defaultView);

  const greeting = new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening';

  const viewLabel: Record<DashView, string> = {
    dispatch: 'dispatch overview',
    management: 'management reports',
    worker: 'personal overview',
  };

  return (
    <div className="space-y-8 animate-slide-up">
      {/* Tier 1 — company standing, visible to every role */}
      <CompanyStandingCard />

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="page-title">
            Good {greeting}, {user?.firstName || user?.displayName || user?.username}
          </h1>
          <p className="text-subtle mt-1">Here's your {viewLabel[activeView]} for today.</p>
        </div>

        {/* Admin view switcher */}
        {isAdmin && (
          <div className="flex items-center gap-1 bg-accent rounded-xl p-1 text-sm">
            {(['dispatch', 'management', 'worker'] as DashView[]).map(v => (
              <button
                key={v}
                onClick={() => setActiveView(v)}
                className={`px-3 py-1.5 rounded-lg font-medium capitalize transition-colors ${
                  activeView === v
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {[
          { label: 'Role', value: groups.join(', ') || 'Pending', icon: Users, color: 'text-primary' },
          { label: 'Today', value: new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric' }), icon: Calendar, color: 'text-info' },
        ].map(stat => (
          <div key={stat.label} className="card-elevated flex items-center gap-4">
            <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-primary/5">
              <stat.icon className={`w-5 h-5 ${stat.color}`} />
            </div>
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider">{stat.label}</p>
              <p className="text-sm font-semibold text-foreground mt-0.5 capitalize">{stat.value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Role-branched content */}
      {activeView === 'dispatch'   && <DispatchView />}
      {activeView === 'management' && <ManagementView />}
      {activeView === 'worker'     && <WorkerView />}
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <NotificationProvider>
      <Router>
        <Routes>
          <Route path="/login"    element={<Login />} />
          <Route path="/register" element={<Register />} />
          
          {/* Setup gate — full-screen, no navbar, shown to admins before company is configured */}
          <Route
            path="/setup"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <CompanySettings isOnboarding />
              </ProtectedRoute>
            }
          />

          <Route element={<Layout />}>
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <RoleRedirect />
                </ProtectedRoute>
              }
            />
            <Route
              path="/dispatch-home"
              element={
                <ProtectedRoute allowedRoles={['admin', 'dispatch']}>
                  <DispatchHome />
                </ProtectedRoute>
              }
            />
            <Route
              path="/dispatch"
              element={
                <ProtectedRoute allowedRoles={['admin', 'dispatch']}>
                  <DispatchDashboard />
                </ProtectedRoute>
              }
            />
            <Route
              path="/assets"
              element={
                <ProtectedRoute allowedRoles={['admin', 'management']}>
                  <Assets />
                </ProtectedRoute>
              }
            />
            <Route path="/schedule" element={<ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'management', 'admin', 'captain']}><Schedule /></ProtectedRoute>} />
            {/* field-ops: drivers submit; trainers/trainees see AP card; walkers see self-performance; oversight roles see summary */}
            <Route path="/field-ops" element={<ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin', 'captain']}><FieldOps /></ProtectedRoute>} />
            {/* schedule-changes: dispatch excluded — not their job */}
            <Route
              path="/schedule-changes"
              element={
                <ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'admin', 'captain']}>
                  <ScheduleChanges />
                </ProtectedRoute>
              }
            />
            {/* incidents: all authenticated roles can file or view incidents */}
            <Route path="/incidents" element={<ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin', 'captain']}><Incidents /></ProtectedRoute>} />
            <Route
              path="/preferences"
              element={
                <ProtectedRoute>
                  <Preferences />
                </ProtectedRoute>
              }
            />
            <Route
              path="/account"
              element={
                <ProtectedRoute>
                  <Account />
                </ProtectedRoute>
              }
            />
            <Route
              path="/notifications"
              element={
                <ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin']}>
                  <NotificationsHistory />
                </ProtectedRoute>
              }
            />
            <Route
              path="/trainer-dashboard"
              element={
                <ProtectedRoute allowedRoles={['trainer', 'admin']}>
                  <TrainerDashboard />
                </ProtectedRoute>
              }
            />
            <Route
              path="/trainee-management"
              element={
                <ProtectedRoute allowedRoles={['admin', 'management']}>
                  <TraineeManagement />
                </ProtectedRoute>
              }
            />
            <Route
              path="/my-training"
              element={
                <ProtectedRoute allowedRoles={['trainee']}>
                  <TraineeDashboard />
                </ProtectedRoute>
              }
            />
            <Route
              path="/management"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <ManagementView />
                </ProtectedRoute>
              }
            />
            <Route
              path="/vehicle-compliance"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <VehicleCompliance />
                </ProtectedRoute>
              }
            />
            <Route
              path="/walker-performance"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <WalkerPerformance />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin"
              element={
                <ProtectedRoute allowedRoles={['admin']}>
                  <AdminDashboard />
                </ProtectedRoute>
              }
            />
            <Route
              path="/trainer-marks"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <TrainerMarks />
                </ProtectedRoute>
              }
            />
            <Route
              path="/training-curriculum"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <TrainingCurriculum />
                </ProtectedRoute>
              }
            />
            <Route
              path="/phase4-observation"
              element={
                <ProtectedRoute allowedRoles={['trainer', 'admin']}>
                  <Phase4Observation />
                </ProtectedRoute>
              }
            />
            <Route
              path="/my-quiz"
              element={
                <ProtectedRoute allowedRoles={['trainee']}>
                  <GraduationQuiz />
                </ProtectedRoute>
              }
            />
            <Route
              path="/graduation-quiz/:quizId"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <GraduationQuizReview />
                </ProtectedRoute>
              }
            />
            <Route
              path="/feedback"
              element={
                <ProtectedRoute allowedRoles={['admin']}>
                  <FeedbackAdmin />
                </ProtectedRoute>
              }
            />
            <Route
              path="/settings"
              element={
                <ProtectedRoute allowedRoles={['admin']}>
                  <CompanySettings />
                </ProtectedRoute>
              }
            />
            <Route
              path="/audit"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <AuditLog />
                </ProtectedRoute>
              }
            />
            <Route
              path="/operations-analytics"
              element={
                <ProtectedRoute allowedRoles={['dispatch', 'management', 'admin']}>
                  <OperationsAnalytics />
                </ProtectedRoute>
              }
            />
            <Route
              path="/driver-surveys"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <DriverSurveys />
                </ProtectedRoute>
              }
            />
            <Route
              path="/anchor-points"
              element={
                <ProtectedRoute allowedRoles={['driver', 'dispatch', 'admin', 'captain']}>
                  <AnchorPoints />
                </ProtectedRoute>
              }
            />
            <Route path="/captain-dashboard" element={<ProtectedRoute allowedRoles={['captain', 'admin']}><CaptainDashboard /></ProtectedRoute>} />
            <Route
              path="/crew-status"
              element={
                <ProtectedRoute allowedRoles={['admin', 'dispatch', 'management', 'driver', 'trainer', 'captain']}>
                  <CrewStatus />
                </ProtectedRoute>
              }
            />
            {/* ADR-245 lookup now lives as a TAB of Field Packages — the three
                package operations are one job for one person. Redirect rather than
                delete: this path has been in the nav, so bookmarks and older links
                exist and should land somewhere useful instead of a 404. */}
            <Route path="/package-lookup" element={<Navigate to="/field-packages" replace />} />
            {/* ADR-246 — field-added package oversight + manual assignment.
                Dispatch-readable BY DESIGN: GET /audit is management+admin, so
                pointing dispatch at the audit log would not actually work. */}
            <Route
              path="/field-packages"
              element={
                <ProtectedRoute allowedRoles={['dispatch', 'management', 'admin']}>
                  <FieldPackages />
                </ProtectedRoute>
              }
            />
            {/* Consolidated Scorecards tab. The four sub-views keep their own
                routes below so existing links and the "Open in Appeals" deep
                link stay valid; only the NAV collapsed to one entry. */}
            <Route
              path="/scorecards"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin', 'dispatch']}>
                  <Scorecards />
                </ProtectedRoute>
              }
            />
            {/* Tier 3 — individual scorecards; dispatch excluded (ADR-242) */}
            <Route
              path="/scorecard-roster"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <ScorecardRoster />
                </ProtectedRoute>
              }
            />
            {/* Tier 4 — appeals reach individual scorecard data, so management+admin only */}
            <Route
              path="/scorecard-appeals"
              element={
                <ProtectedRoute allowedRoles={['management', 'admin']}>
                  <ScorecardAppeals />
                </ProtectedRoute>
              }
            />
            <Route
              path="/scorecard-entry"
              element={
                <ProtectedRoute allowedRoles={['admin', 'management']}>
                  <ScorecardEntry />
                </ProtectedRoute>
              }
            />
            <Route
              path="/building-profiles"
              element={
                <ProtectedRoute allowedRoles={['walker', 'trainee', 'trainer', 'driver', 'dispatch', 'management', 'admin', 'captain']}>
                  <BuildingProfilesPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/my-truck-buildings"
              element={
                <ProtectedRoute allowedRoles={['walker', 'trainee', 'trainer', 'dispatch', 'management', 'admin', 'captain']}>
                  <TruckBuildingsPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/sort"
              element={
                <ProtectedRoute allowedRoles={['driver', 'dispatch', 'admin']}>
                  <SortPage />
                </ProtectedRoute>
              }
            />
            {/* ADR-273. Roles come from navConfig so the tab and the gate cannot
                drift — the failure the 2026-07-03 access audit fixed. */}
            <Route
              path="/sort-metrics"
              element={
                <ProtectedRoute allowedRoles={routeRoles('/sort-metrics')}>
                  <SortMetricsPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/sort/print"
              element={
                <ProtectedRoute allowedRoles={['driver', 'trainer', 'dispatch', 'management', 'admin']}>
                  <PrintLoadSheets />
                </ProtectedRoute>
              }
            />
            <Route
              path="/sort/returns-print"
              element={
                <ProtectedRoute allowedRoles={['dispatch', 'management', 'admin']}>
                  <ReturnsManifestPrint />
                </ProtectedRoute>
              }
            />
            <Route
              path="/walker-sort"
              element={
                <ProtectedRoute allowedRoles={['driver', 'trainer', 'dispatch', 'management', 'admin', 'captain']}>
                  <WalkerSortMonitor />
                </ProtectedRoute>
              }
            />
            <Route
              path="/my-route"
              element={
                <ProtectedRoute allowedRoles={['walker', 'trainee']}>
                  <MyRoute />
                </ProtectedRoute>
              }
            />
            <Route
              path="/gear"
              element={
                <ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin', 'captain']}>
                  <GearRequest />
                </ProtectedRoute>
              }
            />
          </Route>

          {/* Super admin — separate layout, no Navbar, violet ambient */}
          <Route
            element={
              <ProtectedRoute allowedRoles={['super_admin']}>
                <SuperAdminLayout />
              </ProtectedRoute>
            }
          >
            <Route path="/superadmin/companies" element={<Companies />} />
            <Route path="/superadmin/companies/:companyId" element={<CompanyDetailWithKey />} />
            <Route path="/superadmin/alerts" element={<PlatformAlerts />} />
            <Route path="/superadmin/account" element={<Account />} />
            <Route path="/superadmin" element={<Navigate to="/superadmin/companies" replace />} />
          </Route>

        </Routes>
      </Router>
      </NotificationProvider>
    </AuthProvider>
  );
}

export default App;
