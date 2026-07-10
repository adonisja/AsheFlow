import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import InAppBrowser from 'react-native-inappbrowser-reborn';
import { Linking } from 'react-native';
import { Platform } from 'react-native';
import { COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, ASHEFLOW_API_URL, ASHEFLOW_LAN_IP, COGNITO_OAUTH_DOMAIN, COGNITO_REDIRECT_URI } from '@env';
import { getValidIdToken, touchLastActive, clearTokens } from '../api/tokenRefresh';

const USER_POOL_ID    = COGNITO_USER_POOL_ID ?? '';
const CLIENT_ID       = COGNITO_CLIENT_ID ?? '';
const API_BASE        = ASHEFLOW_API_URL
  ? ASHEFLOW_API_URL
  : Platform.OS === 'android'
    ? 'http://10.0.2.2:8000/api/v1'
    : `http://${ASHEFLOW_LAN_IP ?? '192.168.1.1'}:8000/api/v1`;
const REGION          = USER_POOL_ID.split('_')[0] ?? 'us-east-2';
const COGNITO_ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;
const OAUTH_DOMAIN    = COGNITO_OAUTH_DOMAIN ?? '';
const REDIRECT_URI    = COGNITO_REDIRECT_URI ?? 'asheflow://callback';

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
  signInWithProvider: (provider: 'Discord' | 'Google') => Promise<void>;
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
      // Refreshes a stale ID token via the Cognito refresh token, or returns
      // null (tokens cleared) when the inactivity window has lapsed — so a
      // crash/restart re-enters the app silently within the window and forces
      // re-login after it.
      const idToken = await getValidIdToken();
      if (!idToken) { setLoading(false); return; }
      await touchLastActive();
      const base = buildUserFromToken(idToken);
      setUser(base);
      setLoading(false);
      resolveFirstName(idToken, base.firstName).then(firstName =>
        setUser(prev => prev ? { ...prev, firstName } : prev)
      );
    } catch {
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
    await storeTokens(AuthenticationResult);
    const base = buildUserFromToken(AuthenticationResult.IdToken);
    setUser(base);
    resolveFirstName(AuthenticationResult.IdToken, base.firstName).then(firstName =>
      setUser(prev => prev ? { ...prev, firstName } : prev)
    );
  }, []);

  const signInWithProvider = useCallback(async (provider: 'Discord' | 'Google') => {
    const authUrl = buildHostedUiUrl(provider);

    const available = await InAppBrowser.isAvailable();
    if (!available) {
      // Fallback: open system browser — user must manually return to app
      await Linking.openURL(authUrl);
      return;
    }

    const result = await InAppBrowser.openAuth(authUrl, REDIRECT_URI, {
      // iOS
      dismissButtonStyle: 'cancel',
      preferredBarTintColor: '#5B21B6',
      preferredControlTintColor: '#ffffff',
      readerMode: false,
      animated: true,
      modalEnabled: true,
      enableBarCollapsing: false,
      // Android
      showTitle: false,
      toolbarColor: '#5B21B6',
      secondaryToolbarColor: 'black',
      navigationBarColor: 'black',
      navigationBarDividerColor: 'white',
      enableUrlBarHiding: true,
      enableDefaultShare: false,
      forceCloseOnRedirection: false,
    });

    if (result.type !== 'success' || !result.url) {
      throw new Error('Sign in was cancelled or failed.');
    }

    // Extract the authorization code from the redirect URL
    const redirectUrl = new URL(result.url);
    const code = redirectUrl.searchParams.get('code');
    const errorParam = redirectUrl.searchParams.get('error');
    const errorDesc = redirectUrl.searchParams.get('error_description');

    if (errorParam) {
      // Lambda pre-signup rejection surfaces here as an error in the redirect
      const friendly = errorDesc?.includes('No AsheFlow account')
        ? 'No AsheFlow account found for this email. Ask your dispatcher to create your account first.'
        : errorDesc ?? 'Sign in failed. Please try again.';
      throw new Error(friendly);
    }

    if (!code) {
      throw new Error('No authorization code returned. Please try again.');
    }

    // Exchange authorization code for tokens
    const tokens = await exchangeCodeForTokens(code);
    await storeTokens(tokens);
    const base = buildUserFromToken(tokens.IdToken);
    setUser(base);
    resolveFirstName(tokens.IdToken, base.firstName).then(firstName =>
      setUser(prev => prev ? { ...prev, firstName } : prev)
    );
  }, []);

  const signOut = useCallback(async () => {
    await clearTokens();
    setUser(null);
  }, []);

  const hasRole = useCallback(
    (...roles: string[]) => roles.some(r => user?.groups.includes(r)),
    [user],
  );

  return (
    <AuthContext.Provider value={{
      user, isLoading, isAuthenticated: !!user,
      signIn, signInWithProvider, signOut, hasRole,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

const AUTH_FALLBACK: AuthContextType = {
  user: null,
  isLoading: true,
  isAuthenticated: false,
  signIn: async () => { throw new Error('useAuth must be used inside AuthProvider'); },
  signInWithProvider: async () => { throw new Error('useAuth must be used inside AuthProvider'); },
  signOut: async () => {},
  hasRole: () => false,
};

export function useAuth() {
  return useContext(AuthContext) ?? AUTH_FALLBACK;
}

// ── helpers ───────────────────────────────────────────────────────────────────

function buildHostedUiUrl(provider: 'Discord' | 'Google'): string {
  const params = new URLSearchParams({
    client_id:     CLIENT_ID,
    response_type: 'code',
    scope:         'email openid profile',
    redirect_uri:  REDIRECT_URI,
    identity_provider: provider,
  });
  return `https://${OAUTH_DOMAIN}/oauth2/authorize?${params.toString()}`;
}

async function exchangeCodeForTokens(code: string): Promise<{
  AccessToken: string;
  IdToken: string;
  RefreshToken: string;
}> {
  const body = new URLSearchParams({
    grant_type:   'authorization_code',
    client_id:    CLIENT_ID,
    code,
    redirect_uri: REDIRECT_URI,
  });

  const res = await fetch(`https://${OAUTH_DOMAIN}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });

  const data = await res.json();
  if (!res.ok || data.error) {
    throw new Error(data.error_description ?? data.error ?? 'Token exchange failed');
  }

  return {
    AccessToken:  data.access_token,
    IdToken:      data.id_token,
    RefreshToken: data.refresh_token,
  };
}

async function storeTokens(tokens: {
  AccessToken: string;
  IdToken: string;
  RefreshToken: string;
}) {
  await AsyncStorage.setItem('asheflow_access_token',  tokens.AccessToken);
  await AsyncStorage.setItem('asheflow_id_token',      tokens.IdToken);
  await AsyncStorage.setItem('asheflow_refresh_token', tokens.RefreshToken);
  await touchLastActive();
}

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
  const payload = parseJwtPayload(idToken);
  const email   = payload.email ?? '';
  const cognitoUsername = payload['cognito:username'] ?? email.split('@')[0];
  return {
    id:        payload.sub ?? '',
    email,
    username:  cognitoUsername,
    groups:    payload['cognito:groups'] ?? [],
    firstName: cognitoUsername,
  };
}
