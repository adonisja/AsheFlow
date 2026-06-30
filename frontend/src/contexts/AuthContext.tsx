import React, { createContext, useContext, useEffect, useState } from 'react';
import { getCurrentUser, fetchAuthSession } from 'aws-amplify/auth';
import { Hub } from 'aws-amplify/utils';
import { getUserGroups } from '../utils/auth';
import axiosClient from '../api/axiosClient';

interface AuthUser {
  username: string;
  userId: string;
  signInDetails?: Record<string, any>;
  displayName?: string;
  firstName?: string;
}

interface AuthContextType {
  user: AuthUser | null;
  groups: string[];
  isAuthenticated: boolean;
  isLoading: boolean;
  isConfigured: boolean;
  refreshConfigured: () => Promise<void>;
  federatedError: string | null;
  clearFederatedError: () => void;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isConfigured, setIsConfigured] = useState(true);
  const [federatedError, setFederatedError] = useState<string | null>(null);

  const refreshConfigured = async () => {
    try {
      const res = await axiosClient.get<{ is_configured: boolean }>('/companies/my-config');
      setIsConfigured(res.data.is_configured);
    } catch {
      // Non-admins will 403 here — treat as configured so gate doesn't block them
      setIsConfigured(true);
    }
  };

  const clearFederatedError = () => setFederatedError(null);

  const checkAuth = async () => {
    setIsLoading(true);
    try {
      // 1. Get the current user and warm the token cache in parallel.
      // fetchAuthSession must complete before isLoading clears — the axios interceptor
      // calls it on every request, and if it hasn't resolved yet the request goes out
      // with no Authorization header, causing a 422 from OAuth2PasswordBearer.
      const [currentUser] = await Promise.all([
        getCurrentUser(),
        fetchAuthSession(),
      ]);

      // New pool: currentUser.username is the Cognito username (e.g. "danny.rivera")
      // Use it as the display name fallback; /employees/me first name takes priority.
      const displayName = currentUser.username ?? undefined;

      // 2. Decode the JWT to get their Cognito groups using our utility
      const userGroups = await getUserGroups();
      setGroups(userGroups);

      // Resolve DB first name — skip for super_admin (no Employee row)
      let firstName = displayName;
      if (!userGroups.includes('super_admin')) {
        try {
          const res = await axiosClient.get<{ name: string }>('/employees/me');
          firstName = res.data?.name?.split(' ')[0] ?? displayName;
        } catch {
          // keep Cognito username as fallback
        }
      }

      setUser({ ...currentUser, displayName, firstName });

      // 3. For admins, check if the company has completed setup
      if (userGroups.includes('admin')) {
        try {
          const res = await axiosClient.get<{ is_configured: boolean }>('/companies/my-config');
          setIsConfigured(res.data.is_configured);
        } catch {
          setIsConfigured(true);
        }
      } else {
        setIsConfigured(true);
      }

    } catch (error) {
      // If this throws, the user is simply not logged in.
      setUser(null);
      setGroups([]);
      setIsConfigured(true);
    } finally {
      // We are done checking against AWS
      setIsLoading(false);
    }
  };

  useEffect(() => {
    checkAuth();

    const unsubscribe = Hub.listen('auth', ({ payload }) => {
      const event = payload.event as string;
      switch (event) {
        case 'signedIn':
          checkAuth();
          break;
        case 'signedOut':
          setUser(null);
          setGroups([]);
          break;
        case 'signIn_failure': {
          // Fired when a federated flow is rejected — e.g. pre-signup Lambda blocks the user.
          // Extract the human-readable message from the error description if present.
          const raw = (payload as any)?.data?.error?.message ?? (payload as any)?.data?.message ?? '';
          const friendly = raw.includes('No AsheFlow account')
            ? 'No AsheFlow account found for this email. Ask your dispatcher to create your account first.'
            : raw || 'Sign in failed. Please try again.';
          setFederatedError(friendly);
          break;
        }
      }
    });

    return unsubscribe;
  }, []);

  const value = {
    user,
    groups,
    isAuthenticated: !!user,
    isLoading,
    isConfigured,
    refreshConfigured,
    federatedError,
    clearFederatedError,
    checkAuth,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

// Create a custom hook so we don't have to import useContext everywhere
export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
