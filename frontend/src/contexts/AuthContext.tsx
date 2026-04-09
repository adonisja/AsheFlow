import React, { createContext, useContext, useEffect, useState } from 'react';
import { getCurrentUser, fetchAuthSession } from 'aws-amplify/auth';
import { Hub } from 'aws-amplify/utils';
import { getUserGroups } from '../utils/auth';

interface AuthUser {
  username: string;
  userId: string;
  signInDetails?: Record<string, any>;
  displayName?: string;
}

interface AuthContextType {
  user: AuthUser | null;
  groups: string[];
  isAuthenticated: boolean;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider = ({ children }: { children: React.ReactNode }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [groups, setGroups] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const checkAuth = async () => {
    try {
      // 1. Get the current user
      const currentUser = await getCurrentUser();
      
      const session = await fetchAuthSession();
      const email = session.tokens?.idToken?.payload?.email as string | undefined;
      const displayName = email ? email.split('@')[0] : undefined;
      
      setUser({ ...currentUser, displayName });
      
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
      }
    });

    return unsubscribe;
  }, []);

  const value = {
    user,
    groups,
    isAuthenticated: !!user,
    isLoading,
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
