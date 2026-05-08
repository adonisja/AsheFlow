import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, ASHEFLOW_API_URL } from '@env';

const USER_POOL_ID = COGNITO_USER_POOL_ID ?? '';
const CLIENT_ID    = COGNITO_CLIENT_ID ?? '';
const API_BASE     = ASHEFLOW_API_URL ?? 'http://localhost:8000/api/v1';
// Derive region from pool id (format: region_xxxxxxx)
const REGION       = USER_POOL_ID.split('_')[0] ?? 'us-east-2';
const COGNITO_ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;

type AuthUser = {
  id: string;
  email: string;
  username: string;
  groups: string[];
  firstName: string;
};

type AuthContextType = {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser]         = useState<AuthUser | null>(null);
  const [isLoading, setLoading] = useState(true);

  useEffect(() => { restoreSession(); }, []);

  const restoreSession = async () => {
    try {
      const idToken = await AsyncStorage.getItem('asheflow_id_token');
      if (!idToken) { setLoading(false); return; }
      const base = buildUserFromToken(idToken);
      // Show the app immediately — patch first name in background
      setUser(base);
      setLoading(false);
      resolveFirstName(idToken, base.firstName).then(firstName =>
        setUser(prev => prev ? { ...prev, firstName } : prev)
      );
    } catch {
      // corrupted storage — start fresh
      setLoading(false);
    }
  };

  const signIn = useCallback(async (username: string, password: string) => {
    const res = await fetch(COGNITO_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
      },
      body: JSON.stringify({
        AuthFlow:       'USER_PASSWORD_AUTH',
        ClientId:       CLIENT_ID,
        AuthParameters: { USERNAME: username, PASSWORD: password },
      }),
    });

    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.message ?? data.__type ?? 'Sign in failed');
    }

    const { AuthenticationResult } = data;
    await AsyncStorage.setMany({
      asheflow_access_token:  AuthenticationResult.AccessToken,
      asheflow_id_token:      AuthenticationResult.IdToken,
      asheflow_refresh_token: AuthenticationResult.RefreshToken,
    });

    const base = buildUserFromToken(AuthenticationResult.IdToken);
    setUser(base);
    resolveFirstName(AuthenticationResult.IdToken, base.firstName).then(firstName =>
      setUser(prev => prev ? { ...prev, firstName } : prev)
    );
  }, []);

  const signOut = useCallback(async () => {
    await AsyncStorage.removeMany([
      'asheflow_access_token',
      'asheflow_id_token',
      'asheflow_refresh_token',
    ]);
    setUser(null);
  }, []);

  const hasRole = useCallback(
    (...roles: string[]) => roles.some(r => user?.groups.includes(r)),
    [user],
  );

  return (
    <AuthContext.Provider value={{ user, isLoading, isAuthenticated: !!user, signIn, signOut, hasRole }}>
      {children}
    </AuthContext.Provider>
  );
}

const AUTH_FALLBACK: AuthContextType = {
  user: null,
  isLoading: true,
  isAuthenticated: false,
  signIn: async () => { throw new Error('useAuth must be used inside AuthProvider'); },
  signOut: async () => {},
  hasRole: () => false,
};

export function useAuth() {
  return useContext(AuthContext) ?? AUTH_FALLBACK;
}

// ── helpers ──────────────────────────────────────────────────────────────────

function parseJwtPayload(token: string): Record<string, any> {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(base64));
  } catch {
    return {};
  }
}

async function resolveFirstName(idToken: string, fallback: string): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/employees/me`, {
      headers: { Authorization: `Bearer ${idToken}` },
    });
    if (!res.ok) return fallback;
    const data = await res.json();
    return (data.name as string | undefined)?.split(' ')[0] ?? fallback;
  } catch {
    return fallback;
  }
}

function buildUserFromToken(idToken: string): AuthUser {
  const payload  = parseJwtPayload(idToken);
  const email    = payload.email ?? '';
  const cognitoUsername = payload['cognito:username'] ?? email.split('@')[0];
  return {
    id:        payload.sub ?? '',
    email,
    username:  cognitoUsername,
    groups:    payload['cognito:groups'] ?? [],
    firstName: cognitoUsername, // placeholder until DB name resolves via /employees/me
  };
}
