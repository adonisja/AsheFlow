import { useCallback, useRef } from 'react';
import { useAuth } from '@contexts/AuthContext';
import apiClient from '@api/client';

/**
 * Returns a function that resolves the caller's Employee DB UUID.
 *
 * The Cognito token sub (user.id from AuthContext) is NOT the same as the
 * Employee.id UUID stored in the database. Every API route that accepts an
 * employee_id path/query param expects the DB UUID, not the Cognito sub.
 *
 * The resolved value is cached in a ref so /employees/me is only called once
 * per component mount regardless of how many times fetchId() is called.
 */
export function useEmployeeId() {
  const { user } = useAuth();
  const cached   = useRef<string | null>(null);

  const fetchId = useCallback(async (): Promise<string | null> => {
    if (!user) return null;
    if (cached.current) return cached.current;
    try {
      const res      = await apiClient.get('/employees/me');
      cached.current = res.data.id as string;
      return cached.current;
    } catch {
      return null;
    }
  }, [user]);

  return { fetchId, cachedId: cached };
}
