import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Login from './components/auth/Login';
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
import OperationsAnalytics from './pages/OperationsAnalytics';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import DispatchView from './components/dashboard/DispatchView';
import ManagementView from './components/dashboard/ManagementView';
import WorkerView from './components/dashboard/WorkerView';
import { Users, Calendar } from 'lucide-react';


const ProtectedRoute = ({ children, allowedRoles = [] }: { children: React.ReactNode, allowedRoles?: string[] }) => {
  const { isAuthenticated, isLoading, groups } = useAuth();

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
  const { groups } = useAuth();
  if (groups.includes('admin'))       return <Navigate to="/admin" replace />;
  if (groups.includes('dispatch'))    return <Navigate to="/dispatch-home" replace />;
  if (groups.includes('management'))  return <Navigate to="/management" replace />;
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
      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="page-title">
            Good {greeting}, {user?.displayName || user?.username}
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
      <Router>
        <Routes>
          <Route path="/login" element={<Login />} />
          
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
            <Route path="/schedule" element={<ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'management', 'admin']}><Schedule /></ProtectedRoute>} />
            {/* field-ops: drivers use check-in/departure/inspections; walkers/trainers/trainees can submit ratings */}
            <Route path="/field-ops" element={<ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'admin']}><FieldOps /></ProtectedRoute>} />
            {/* schedule-changes: dispatch excluded — not their job */}
            <Route
              path="/schedule-changes"
              element={
                <ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'admin']}>
                  <ScheduleChanges />
                </ProtectedRoute>
              }
            />
            {/* incidents: all authenticated roles can file or view incidents */}
            <Route path="/incidents" element={<ProtectedRoute allowedRoles={['driver', 'walker', 'trainer', 'trainee', 'dispatch', 'management', 'admin']}><Incidents /></ProtectedRoute>} />
            <Route
              path="/preferences"
              element={
                <ProtectedRoute>
                  <Preferences />
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
              path="/feedback"
              element={
                <ProtectedRoute allowedRoles={['admin']}>
                  <FeedbackAdmin />
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
          </Route>
          
        </Routes>
      </Router>
    </AuthProvider>
  );
}

export default App;
