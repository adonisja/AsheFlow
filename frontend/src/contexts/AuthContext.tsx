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
  federatedError: string | null;
  clearFederatedError: () => void;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [federatedError, setFederatedError] = useState<string | null>(null);

  const clearFederatedError = () => setFederatedError(null);

  const checkAuth = async () => {
    setIsLoading(true);
    try {
      // 1. Get the current user
      const currentUser = await getCurrentUser();
      
      // New pool: currentUser.username is the Cognito username (e.g. "danny.rivera")
      // Use it as the display name fallback; /employees/me first name takes priority.
      const displayName = currentUser.username ?? undefined;

      // Resolve DB first name before setting user so greeting is correct on first render
      let firstName = displayName;
      try {
        const res = await axiosClient.get<{ name: string }>('/employees/me');
        firstName = res.data?.name?.split(' ')[0] ?? displayName;
      } catch {
        // keep Cognito username as fallback
      }

      setUser({ ...currentUser, displayName, firstName });
      
      // 2. Decode the JWT to get their Cognito groups using our utility
      const userGroups = await getUserGroups();
      setGroups(userGroups);
      
    } catch (error) {
      // If this throws, the user is simply not logged in.
      setUser(null);
      setGroups([]);
    } finally {
      // We are done checking against AWS
      setIsLoading(false);
    }
  };

  useEffect(() => {
    checkAuth();

    const unsubscribe = Hub.listen('auth', ({ payload }) => {
      switch (payload.event) {
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
          const raw = (payload.data as any)?.error?.message ?? (payload.data as any)?.message ?? '';
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
