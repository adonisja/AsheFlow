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
import apiClient from '../api/client';
import { generatedLight } from '@theme/generated-colors';

/** OAuth hosted-UI chrome. Theme-constant on purpose — see usage below. */
const OAUTH_BAR    = generatedLight.brandSurface;
const OAUTH_BAR_FG = generatedLight.brandSurfaceForeground;

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

/** What this company can do (ADR-289), from GET /companies/my-capabilities. */
export type Capabilities = {
  operating_mode: 'full' | 'workforce';
  /** Feature keys. ABSENT = render no entry point for it. Clients gate on these
   *  rather than on operating_mode, so a new mode needs no app release. */
  features: string[];
};

/** A Cognito challenge that sign-in stopped on (ADR-362).
 *
 *  Cognito returns EITHER `AuthenticationResult` OR a `ChallengeName` plus a
 *  `Session`, never both. This client read `AuthenticationResult` unconditionally
 *  and so threw a TypeError on every challenge — including the
 *  NEW_PASSWORD_REQUIRED one a field user hits with a temporary password, which
 *  made that a live bug well before any MFA work.
 *
 *  `session` is single-use and short-lived: each RespondToAuthChallenge returns a
 *  fresh one, so the caller must pass back whatever the LAST response carried. */
export type AuthChallenge = {
  name:
    | 'NEW_PASSWORD_REQUIRED'
    | 'SOFTWARE_TOKEN_MFA'
    | 'EMAIL_OTP'
    | 'SELECT_MFA_TYPE'
    | 'MFA_SETUP';
  session: string;
  username: string;
  /** Which factors the account has, when Cognito asks the user to choose. */
  options?: string[];
  /** Where an emailed code went, e.g. "e***@e***.com". Cognito redacts it. */
  destination?: string;
};

type AuthContextType = {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  /** Resolves to a challenge when one is required, otherwise null. */
  signIn: (username: string, password: string) => Promise<AuthChallenge | null>;
  /** Answer the challenge signIn returned. Resolves to the NEXT challenge when
   *  Cognito chains them (choosing a factor, then entering its code). */
  respondToChallenge: (challenge: AuthChallenge, answer: string) => Promise<AuthChallenge | null>;
  signInWithProvider: (provider: 'Discord' | 'Google') => Promise<void>;
  signOut: () => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
  capabilities: Capabilities | null;
  /** Fails OPEN when capabilities are unknown: a walker on a flaky van
   *  connection must not lose their tabs, and the server enforces every gated
   *  route anyway (RequireMode -> 404). A dead tab is recoverable; a blank app
   *  mid-shift is not. */
  hasFeature: (key: string) => boolean;
};

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser]         = useState<AuthUser | null>(null);
  const [isLoading, setLoading] = useState(true);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);

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

  /** POST one Cognito Identity Provider action. */
  const cognito = useCallback(async (target: string, body: object) => {
    const res = await fetch(COGNITO_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`,
      },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.message ?? data.__type ?? 'Sign in failed');
    }
    return data;
  }, []);

  /** Finish a sign-in, or hand back the challenge that is blocking it.
   *
   *  ADR-362 — Cognito returns EITHER AuthenticationResult OR ChallengeName,
   *  never both. Reading the former unconditionally is what made any challenge
   *  a TypeError here. */
  const settle = useCallback(
    async (data: any, username: string): Promise<AuthChallenge | null> => {
      if (data.ChallengeName) {
        const params = data.ChallengeParameters ?? {};
        return {
          name: data.ChallengeName,
          session: data.Session,
          // Cognito echoes the resolved username for aliased sign-ins (email
          // instead of the username). Answering with what the user typed fails
          // when they differ, so prefer the echo.
          username: params.USER_ID_FOR_SRP ?? username,
          options: params.MFAS_CAN_CHOOSE
            ? JSON.parse(params.MFAS_CAN_CHOOSE)
            : undefined,
          destination: params.CODE_DELIVERY_DESTINATION,
        };
      }

      const { AuthenticationResult } = data;
      if (!AuthenticationResult?.IdToken) {
        // Neither branch: a Cognito response shape we do not know. Say so
        // rather than crashing on a property of undefined.
        throw new Error('Sign in did not complete. Please try again.');
      }
      await storeTokens(AuthenticationResult);
      const base = buildUserFromToken(AuthenticationResult.IdToken);
      setUser(base);
      resolveFirstName(AuthenticationResult.IdToken, base.firstName).then(firstName =>
        setUser(prev => prev ? { ...prev, firstName } : prev)
      );
      return null;
    },
    [],
  );

  const signIn = useCallback(async (username: string, password: string) => {
    const data = await cognito('InitiateAuth', {
      AuthFlow:       'USER_PASSWORD_AUTH',
      ClientId:       CLIENT_ID,
      AuthParameters: { USERNAME: username, PASSWORD: password },
    });
    return settle(data, username);
  }, [cognito, settle]);

  const respondToChallenge = useCallback(
    async (challenge: AuthChallenge, answer: string) => {
      // Each challenge names its own answer key; a wrong key is a 400 that reads
      // like a bad code.
      const responses: Record<string, string> = { USERNAME: challenge.username };
      switch (challenge.name) {
        case 'NEW_PASSWORD_REQUIRED':  responses.NEW_PASSWORD  = answer; break;
        case 'SOFTWARE_TOKEN_MFA':     responses.SOFTWARE_TOKEN_MFA_CODE = answer; break;
        case 'EMAIL_OTP':              responses.EMAIL_OTP_CODE = answer; break;
        case 'SELECT_MFA_TYPE':        responses.ANSWER = answer; break;
        default:
          throw new Error(`Unsupported sign-in step: ${challenge.name}`);
      }

      const data = await cognito('RespondToAuthChallenge', {
        ClientId:          CLIENT_ID,
        ChallengeName:     challenge.name,
        Session:           challenge.session,
        ChallengeResponses: responses,
      });
      // Chained on purpose: SELECT_MFA_TYPE resolves to another challenge
      // (the code for the chosen factor) rather than to tokens.
      return settle(data, challenge.username);
    },
    [cognito, settle],
  );

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
      // `brandSurface` is theme-CONSTANT by design: the OAuth browser is a
        // separate process that cannot follow an in-app theme change mid-flow,
        // and it is the same navy as the sign-in hero. Was '#5B21B6' — a third
        // violet matching neither `brand` nor `primary`.
        preferredBarTintColor: OAUTH_BAR,
      preferredControlTintColor: OAUTH_BAR_FG,
      readerMode: false,
      animated: true,
      modalEnabled: true,
      enableBarCollapsing: false,
      // Android
      showTitle: false,
      toolbarColor: OAUTH_BAR,
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
    setCapabilities(null);
  }, []);

  // ADR-289: load once the user is known, for EVERY role — field staff need this
  // to build their tabs as much as an admin does. A failure leaves it null, which
  // hasFeature reads as "show everything".
  useEffect(() => {
    if (!user) { setCapabilities(null); return; }
    let cancelled = false;
    (async () => {
      try {
        const res = await apiClient.get<Capabilities>('/companies/my-capabilities');
        if (!cancelled) setCapabilities(res.data);
      } catch {
        if (!cancelled) setCapabilities(null);
      }
    })();
    return () => { cancelled = true; };
  }, [user]);

  const hasFeature = useCallback(
    (key: string) => (capabilities ? capabilities.features.includes(key) : true),
    [capabilities],
  );

  const hasRole = useCallback(
    (...roles: string[]) => roles.some(r => user?.groups.includes(r)),
    [user],
  );

  return (
    <AuthContext.Provider value={{
      user, isLoading, isAuthenticated: !!user,
      signIn, respondToChallenge, signInWithProvider, signOut, hasRole,
      capabilities, hasFeature,
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
  respondToChallenge: async () => { throw new Error('useAuth must be used inside AuthProvider'); },
  signInWithProvider: async () => { throw new Error('useAuth must be used inside AuthProvider'); },
  signOut: async () => {},
  hasRole: () => false,
  capabilities: null,
  hasFeature: () => true,
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
