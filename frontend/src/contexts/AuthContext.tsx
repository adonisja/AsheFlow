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

/** What this company can do (ADR-289). Read once at sign-in from
 *  GET /companies/my-capabilities and used to gate navigation. */
export interface Capabilities {
  operating_mode: 'full' | 'workforce';
  /** Feature keys. A key ABSENT means "render no entry point for it". Clients
   *  must not infer features from operating_mode itself, so adding a mode later
   *  needs no client release. */
  features: string[];
}

interface AuthContextType {
  user: AuthUser | null;
  groups: string[];
  isAuthenticated: boolean;
  isLoading: boolean;
  isConfigured: boolean;
  refreshConfigured: () => Promise<void>;
  /** null while loading or when the call failed — see hasFeature. */
  capabilities: Capabilities | null;
  /** True when the feature is available. Returns TRUE while capabilities are
   *  unknown: a transient failure must not blank out a working nav, and every
   *  gated route is enforced server-side anyway (RequireMode → 404). Failing
   *  open here costs a dead tab; failing closed costs a walker their app. */
  hasFeature: (key: string) => boolean;
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
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);

  const refreshConfigured = async () => {
    try {
      const res = await axiosClient.get<{ is_configured: boolean }>('/companies/my-config');
      setIsConfigured(res.data.is_configured);
    } catch {
      // Non-admins will 403 here — treat as configured so gate doesn't block them
      setIsConfigured(true);
    }
  };

  /** Load this company's capabilities. Called for EVERY role, not just admins:
   *  a walker's nav depends on it as much as an admin's. On failure we leave
   *  capabilities null, which hasFeature treats as "show everything". */
  const loadCapabilities = async () => {
    try {
      const res = await axiosClient.get<Capabilities>('/companies/my-capabilities');
      setCapabilities(res.data);
    } catch {
      setCapabilities(null);
    }
  };

  const hasFeature = (key: string) => {
    if (!capabilities) return true;   // unknown → fail open; server still enforces
    return capabilities.features.includes(key);
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

      // Every role, not just admins (ADR-289).
      await loadCapabilities();

    } catch {
      // If this throws, the user is simply not logged in.
      setUser(null);
      setGroups([]);
      setIsConfigured(true);
      setCapabilities(null);
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
          setCapabilities(null);
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
    capabilities,
    hasFeature,
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
