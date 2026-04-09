import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import Login from './components/auth/Login';
import Layout from './components/layout/Layout';
import Preferences from './pages/Preferences';
import Schedule from './pages/Schedule';
import { AuthProvider, useAuth } from './contexts/AuthContext';

const ProtectedRoute = ({ children, allowedRoles = [] }: { children: React.ReactNode, allowedRoles?: string[] }) => {
  const { isAuthenticated, isLoading, groups } = useAuth();

  if (isLoading) {
    return <div className="flex h-screen items-center justify-center">Loading Application...</div>;
  }

  // 1. Not Authenticated? Boot them to login.
  if (!isAuthenticated) return <Navigate to="/login" />;

  // 2. Are they trying to access a page they don't have roles for?
  if (allowedRoles.length > 0) {
    const hasRole = groups.some(role => allowedRoles.includes(role));
    if (!hasRole) {
      return <div className="flex h-screen items-center justify-center text-red-500">Access Denied: Insufficient Permissions (Required: {allowedRoles.join(', ')})</div>;
    }
  }

  return <>{children}</>;
};

function Dashboard() {
  const { user, groups } = useAuth();

  return (
    <div className="bg-white overflow-hidden shadow rounded-lg border border-gray-200">
      <div className="px-4 py-5 sm:p-6">
        <h1 className="text-2xl font-bold text-gray-900">AsheFlow Dashboard</h1>
        <p className="mt-4 text-gray-700">Welcome back, <span className="font-semibold">{user?.displayName || user?.username}</span>!</p>
        <p className="mt-2 text-sm text-gray-500 bg-gray-100 p-3 rounded mt-4">
          Your active roles: <span className="font-mono">{groups.length > 0 ? groups.join(', ') : 'None'}</span>
        </p>
      </div>
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
                  <Dashboard />
                </ProtectedRoute>
              }
            />
            {/* Example Protected Route for Dispatch only */}
            <Route
              path="/dispatch"
              element={
                <ProtectedRoute allowedRoles={['admin', 'management', 'dispatch']}>
                  <div className="p-8"><h1 className="text-2xl font-bold text-red-600">Restricted Dispatch Center</h1></div>
                </ProtectedRoute>
              }
            />
            {/* Asset Management Route */}
            <Route
              path="/assets"
              element={
                <ProtectedRoute allowedRoles={['admin', 'management']}>
                  <div className="p-8"><h1 className="text-2xl font-bold text-blue-600">Assets & Users Management</h1></div>
                </ProtectedRoute>
              }
            />
            <Route path="/schedule" element={<ProtectedRoute><Schedule /></ProtectedRoute>} />
            <Route
              path="/preferences"
              element={
                <ProtectedRoute>
                  <Preferences />
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
