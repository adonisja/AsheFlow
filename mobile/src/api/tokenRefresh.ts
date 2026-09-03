/**
 * Cognito token refresh + inactivity window (shared by client.ts and AuthContext).
 *
 * ID/access tokens expire after 1 hour; the refresh token lives ~30 days.
 * Policy: silently refresh whenever the ID token is expired/near expiry AND
 * the user has been active within INACTIVITY_LIMIT_MS. Past that window the
 * stored tokens are cleared and the user must log in again.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { fetchAuthSession } from 'aws-amplify/auth';
import { COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID } from '@env';

const REGION = (COGNITO_USER_POOL_ID ?? '').split('_')[0] || 'us-east-2';
const COGNITO_ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;
const CLIENT_ID = COGNITO_CLIENT_ID ?? '';

/** Force re-login after this much inactivity (a full shift + margin). */
export const INACTIVITY_LIMIT_MS = 12 * 60 * 60 * 1000;

/** Refresh when the ID token has less than this long left. */
const EXPIRY_MARGIN_MS = 5 * 60 * 1000;

const KEYS = [
  'asheflow_access_token',
  'asheflow_id_token',
  'asheflow_refresh_token',
  'asheflow_last_active',
];

export function tokenExpiresAt(idToken: string): number {
  try {
    const base64 = idToken.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    const payload = JSON.parse(atob(base64));
    return (payload.exp ?? 0) * 1000;
  } catch {
    return 0;
  }
}

export async function touchLastActive(): Promise<void> {
  await AsyncStorage.setItem('asheflow_last_active', String(Date.now()));
}

export async function isWithinActivityWindow(): Promise<boolean> {
  const raw = await AsyncStorage.getItem('asheflow_last_active');
  if (!raw) return true;   // legacy session with no stamp — allow, then stamp
  return Date.now() - Number(raw) < INACTIVITY_LIMIT_MS;
}

export async function clearTokens(): Promise<void> {
  await AsyncStorage.multiRemove(KEYS);
}

// Single-flight: concurrent 401s / interceptor calls share one refresh request.
let inflight: Promise<string | null> | null = null;

/**
 * Returns a valid ID token, refreshing via Cognito if needed.
 * Returns null when there is nothing to refresh with, the inactivity window
 * has lapsed, or Cognito rejects the refresh — callers treat null as
 * "force re-login" (tokens are already cleared in those cases).
 */
export async function getValidIdToken(): Promise<string | null> {
  const idToken = await AsyncStorage.getItem('asheflow_id_token');
  if (!idToken) return null;

  if (tokenExpiresAt(idToken) - Date.now() > EXPIRY_MARGIN_MS) {
    return idToken;   // still fresh
  }

  if (!(await isWithinActivityWindow())) {
    await clearTokens();   // set period of non-activity elapsed → force relog
    return null;
  }

  if (!inflight) {
    inflight = doRefresh().finally(() => { inflight = null; });
  }
  return inflight;
}

async function doRefresh(): Promise<string | null> {
  const refreshToken = await AsyncStorage.getItem('asheflow_refresh_token');
  if (!refreshToken) {
    // ADR-362 — a password sign-in now goes through Amplify, which keeps the
    // refresh token in its OWN storage and never hands it out. No stored token
    // therefore does not mean "signed out"; it means Amplify owns this session.
    // Ask it before destroying anything: clearing here would sign a walker out
    // roughly an hour into their shift.
    try {
      const { tokens } = await fetchAuthSession({ forceRefresh: true });
      const refreshed = tokens?.idToken?.toString();
      if (refreshed) {
        await AsyncStorage.setItem('asheflow_id_token', refreshed);
        const access = tokens?.accessToken?.toString();
        if (access) await AsyncStorage.setItem('asheflow_access_token', access);
        return refreshed;
      }
    } catch {
      // Amplify has no session either — fall through to the real sign-out.
    }
    await clearTokens();
    return null;
  }
  try {
    const res = await fetch(COGNITO_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
      },
      body: JSON.stringify({
        AuthFlow: 'REFRESH_TOKEN_AUTH',
        ClientId: CLIENT_ID,
        AuthParameters: { REFRESH_TOKEN: refreshToken },
      }),
    });
    const data = await res.json();
    const result = data?.AuthenticationResult;
    if (!res.ok || !result?.IdToken) {
      await clearTokens();   // revoked/expired refresh token → force relog
      return null;
    }
    await AsyncStorage.setItem('asheflow_id_token', result.IdToken);
    if (result.AccessToken) {
      await AsyncStorage.setItem('asheflow_access_token', result.AccessToken);
    }
    return result.IdToken as string;
  } catch {
    // Network failure: keep tokens (retry next call), surface the stale one so
    // offline UX degrades to a 401 rather than a hard logout.
    return AsyncStorage.getItem('asheflow_id_token');
  }
}
