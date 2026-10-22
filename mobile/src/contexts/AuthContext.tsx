import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  useRef,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { unregisterFromPush } from '@api/pushRegistration';
import { AppState } from 'react-native';
import { onCredentialsChanged, onMfaEnrolmentRequired } from '@api/client';
import { Platform } from 'react-native';
import { COGNITO_USER_POOL_ID, ASHEFLOW_API_URL, ASHEFLOW_LAN_IP } from '@env';
import {
  signIn as amplifySignIn,
  confirmSignIn as amplifyConfirmSignIn,
  signOut as amplifySignOut,
  fetchAuthSession,
  rememberDevice,
} from 'aws-amplify/auth';
import { getValidIdToken, touchLastActive, clearTokens } from '../api/tokenRefresh';
import apiClient from '../api/client';

/** OAuth hosted-UI chrome. Theme-constant on purpose — see usage below. */

const USER_POOL_ID    = COGNITO_USER_POOL_ID ?? '';
const API_BASE        = ASHEFLOW_API_URL
  ? ASHEFLOW_API_URL
  : Platform.OS === 'android'
    ? 'http://10.0.2.2:8000/api/v1'
    : `http://${ASHEFLOW_LAN_IP ?? '192.168.1.1'}:8000/api/v1`;
const REGION          = USER_POOL_ID.split('_')[0] ?? 'us-east-2';
const COGNITO_ENDPOINT = `https://cognito-idp.${REGION}.amazonaws.com/`;

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

/** GET /employees/me/mfa-status — ADR-377 D2.
 *
 *  Mirrors the web client's MfaStatus in frontend/src/api/types.ts. Declared
 *  locally because mobile has no shared types file; keep the two in step.
 *
 *  `enrolled` is null when Cognito could not be reached. That is deliberately
 *  not false: false means "not enrolled" and past the deadline that BLOCKS, so
 *  an AWS hiccup must never read as a lockout. Render no banner on null.
 */
export type MfaStatus = {
  required: boolean;
  enrolled: boolean | null;
  tier: 'privileged' | 'field' | 'none';
  grace_days_total: number;
  days_remaining: number | null;
  blocked: boolean;
  /** ADR-548. ISO end of an unenrolled privileged account's 24-hour enrolment
   *  window; null otherwise. */
  setup_window_ends_at: string | null;
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
  /** The TOTP shared secret, present only on MFA_SETUP. Without it the screen
   *  can name the challenge but not resolve it, which is what it did before
   *  (ADR-386): it told the user to "set it up on the web app", and the web app
   *  could not handle this challenge either. A closed loop. */
  totpSecret?: string;
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
  signOut: () => Promise<void>;
  hasRole: (...roles: string[]) => boolean;
  capabilities: Capabilities | null;
  /** null means "not known", not "no MFA required" (ADR-377). */
  mfaStatus: MfaStatus | null;
  /** ADR-556 (web: ADR-469). `mfaStatus` null means BOTH "not asked yet" and
   *  "the read failed"; routing must tell them apart. True once the first read
   *  for this user has been ANSWERED, either way -- so the navigator can hold
   *  while unknown, and a failed read still lets the shift start. */
  mfaResolved: boolean;
  /** ADR-556 D5. Why this device was signed out, for the sign-in card to say.
   *  `audience` picks who to contact: a platform account has no manager. */
  sessionNotice: { reason: 'credentials'; audience: 'platform' | 'employee' } | null;
  clearSessionNotice: () => void;
  /** Re-fetch after enrolling, so the blocking screen can release. */
  refreshMfaStatus: () => Promise<void>;
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
  /* null means "not known", NOT "no MFA required" (ADR-377). */
  const [mfaStatus, setMfaStatus] = useState<MfaStatus | null>(null);
  const [mfaResolved, setMfaResolved] = useState(false);
  const [sessionNotice, setSessionNotice] = useState<AuthContextType['sessionNotice']>(null);
  const clearSessionNotice = useCallback(() => setSessionNotice(null), []);

  useEffect(() => { restoreSession(); }, []);

  // ADR-541 D2 — the server ended this session because the password or email
  // was changed (here or on another device). Drop to sign-in and say why.
  // ADR-541 D2 amendment — learn promptly that this session was ended by a
  // password or email change elsewhere. An app sitting in the foreground makes
  // no requests, so check on returning to the foreground and every 60s while
  // active. A credentials_changed 401 is handled by api/client (clears tokens,
  // fires onCredentialsChanged below).
  // ADR-549 D3: platform accounts have no Employee row, so they check their
  // own session stamp instead (the employee path 403s for them, silently).
  const isPlatform = Boolean(user?.groups.some(g => g === 'super_admin' || g === 'platform_support' || g === 'surveyor'));
  useEffect(() => {
    if (!user) return;
    const path = isPlatform ? '/platform/me/session' : '/employees/me/session';
    const check = () => { apiClient.get(path).catch(() => {}); };
    let timer: ReturnType<typeof setInterval> | null =
      AppState.currentState === 'active' ? setInterval(check, 60_000) : null;
    const sub = AppState.addEventListener('change', state => {
      if (state === 'active') {
        check();
        if (!timer) timer = setInterval(check, 60_000);
      } else if (timer) {
        clearInterval(timer); timer = null;
      }
    });
    return () => { sub.remove(); if (timer) clearInterval(timer); };
  }, [user, isPlatform]);

  /* ADR-556 D5. Shown on the sign-in card, not as a native Alert over it: the
     Alert had to be dismissed before the form could be used, and named only
     "password or email" when a two-factor reset ends sessions the same way
     (one stamp, one `credentials_changed` code). Read the audience BEFORE
     clearing the user. */
  const userRef = useRef<AuthUser | null>(null);
  userRef.current = user;
  useEffect(() => onCredentialsChanged(() => {
    const groups = userRef.current?.groups ?? [];
    const platform = groups.some(g => g === 'super_admin' || g === 'platform_support' || g === 'surveyor');
    setSessionNotice({ reason: 'credentials', audience: platform ? 'platform' : 'employee' });
    setUser(null);
    setCapabilities(null);
  }), []);

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

  /* ADR-362 phase 2 — Amplify drives the sign-in protocol now.
     Hand-rolled InitiateAuth was fine while sign-in was one round trip. Device
     tracking ends that: a REMEMBERED device returns a DEVICE_SRP_AUTH challenge
     rather than tokens, and answering it needs a full SRP-6a handshake. Owning
     that crypto in JS is how you get a bug that either fails open or locks every
     walker out of their route.

     The token layer below is deliberately NOT Amplify's. tokenRefresh.ts holds a
     12-hour inactivity limit that is a field-ops rule, not an auth-library
     concept, and api/client.ts reads those keys. Amplify establishes the
     session; we mirror its tokens into the storage that already exists. */
  const adoptSession = useCallback(async (): Promise<null> => {
    const { tokens } = await fetchAuthSession();
    const idToken = tokens?.idToken?.toString();
    const accessToken = tokens?.accessToken?.toString();
    if (!idToken || !accessToken) {
      throw new Error('Sign in did not complete. Please try again.');
    }
    await storeTokens({ IdToken: idToken, AccessToken: accessToken });
    const base = buildUserFromToken(idToken);
    setUser(base);
    resolveFirstName(idToken, base.firstName).then(firstName =>
      setUser(prev => prev ? { ...prev, firstName } : prev)
    );
    return null;
  }, []);

  /** Map an Amplify next-step onto the challenge the login screen renders. */
  const toChallenge = useCallback(
    (step: any, username: string): AuthChallenge | null => {
      switch (step?.signInStep) {
        case 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED':
          return { name: 'NEW_PASSWORD_REQUIRED', session: '', username };
        case 'CONFIRM_SIGN_IN_WITH_TOTP_CODE':
          return { name: 'SOFTWARE_TOKEN_MFA', session: '', username };
        case 'CONFIRM_SIGN_IN_WITH_EMAIL_CODE':
          return {
            name: 'EMAIL_OTP', session: '', username,
            destination: step?.codeDeliveryDetails?.destination,
          };
        case 'CONTINUE_SIGN_IN_WITH_MFA_SELECTION':
          return {
            name: 'SELECT_MFA_TYPE', session: '', username,
            options: step?.allowedMFATypes ?? [],
          };
        case 'CONTINUE_SIGN_IN_WITH_TOTP_SETUP':
          return {
            name: 'MFA_SETUP', session: '', username,
            totpSecret: step?.totpSetupDetails?.sharedSecret,
          };
        default:
          return null;
      }
    },
    [],
  );

  const signIn = useCallback(async (username: string, password: string) => {
    // A stale Amplify session makes signIn throw UserAlreadyAuthenticated
    // rather than starting a new sign-in.
    try { await amplifySignOut(); } catch { /* nothing to sign out of */ }

    const res = await amplifySignIn({
      username,
      password,
      options: { authFlowType: 'USER_PASSWORD_AUTH' },
    });
    if (res.isSignedIn) return adoptSession();
    const next = toChallenge(res.nextStep, username);
    if (next) return next;
    throw new Error(
      `This account needs a sign-in step this app does not support yet (${res.nextStep?.signInStep}).`,
    );
  }, [adoptSession, toChallenge]);

  const respondToChallenge = useCallback(
    async (challenge: AuthChallenge, answer: string) => {
      const res = await amplifyConfirmSignIn({ challengeResponse: answer });
      if (res.isSignedIn) {
        // Trust this device so the next sign-in skips the challenge (ADR-362 D4).
        // Best-effort: a failure here costs an extra prompt, never a blocked
        // sign-in, so it must not reject the session that already succeeded.
        try { await rememberDevice(); } catch { /* re-prompt next time */ }
        return adoptSession();
      }
      // Amplify chains: choosing a factor resolves to the challenge for its code.
      return toChallenge(res.nextStep, challenge.username);
    },
    [adoptSession, toChallenge],
  );


  const signOut = useCallback(async () => {
    // ADR-487 D5. BEFORE clearTokens: the revoke is an authenticated DELETE,
    // and afterwards it would 401 — leaving this phone receiving the previous
    // user's notifications. Best effort and never throws, so sign-out cannot
    // be blocked by push.
    await unregisterFromPush();
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

  /* ADR-377 D2/D3 — starts the MFA grace clock and trims the remembered-device
     fleet. Both are server SIDE-EFFECTS of this GET, not just a read: the clock
     is stamped on the first call after enforcement ships, and eviction runs
     here because no Cognito trigger fires on ConfirmDevice.

     Mobile matters more than web for the clock. A walker may never open the web
     app, so without this their 14-day window would never START -- and then
     begin the day someone finally signs them in on a desktop.

     Same shape as the capabilities load above: keyed on `user`, cancellable,
     and a failure leaves null. `null` means "not known", NOT "no MFA required";
     a banner is worth nothing if failing to fetch it blocks a shift at 05:00. */
  const userId = user?.id ?? null;
  useEffect(() => {
    if (!userId) { setMfaStatus(null); setMfaResolved(false); return; }
    let cancelled = false;
    /* ADR-556: the navigator now routes on this, so it must not render the app
       while the answer is still in flight -- an unenrolled account saw the
       survey register before the setup screen replaced it. The 05:00 property
       is kept by the catch (a failure is an answer: null, not blocked) and by
       apiClient's 10 s timeout (a hung read cannot hold the spinner forever). */
    setMfaResolved(false);
    (async () => {
      try {
        const res = await apiClient.get<MfaStatus>('/employees/me/mfa-status');
        if (!cancelled) setMfaStatus(res.data);
      } catch {
        if (!cancelled) setMfaStatus(null);
      } finally {
        if (!cancelled) setMfaResolved(true);
      }
    })();
    return () => { cancelled = true; };
    /* Keyed on the account, not the object: sign-in sets `user` twice (base,
       then firstName), and re-running on the second would flip mfaResolved
       back to false and remount the whole app under the spinner. */
  }, [userId]);

  /* ADR-556 D2. The server just refused a call because this account must enrol.
     Re-read the full status (MfaRequiredScreen words itself from `tier` and the
     deadline); if that read fails too, the refusal itself is the answer, so mark
     it blocked rather than leave the person in a shell where every call errors. */
  useEffect(() => onMfaEnrolmentRequired(() => {
    void (async () => {
      try {
        const res = await apiClient.get<MfaStatus>('/employees/me/mfa-status');
        setMfaStatus({ ...res.data, blocked: true });
      } catch {
        setMfaStatus(prev => prev ? { ...prev, blocked: true } : {
          required: true, enrolled: false, tier: 'privileged', grace_days_total: 0,
          days_remaining: 0, setup_window_ends_at: null, blocked: true,
        });
      }
      setMfaResolved(true);
    })();
  }), []);

  /* ADR-381 D2 — the blocking screen calls this after enrolling, so the app
     lets them through without a sign-out/sign-in round trip. Failure leaves the
     previous value rather than nulling it: on the blocked path, null would
     unblock someone whose enrolment we could not confirm. */
  const refreshMfaStatus = useCallback(async () => {
    try {
      const res = await apiClient.get<MfaStatus>('/employees/me/mfa-status');
      setMfaStatus(res.data);
    } catch {
      /* keep the last known status */
    }
  }, []);

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
      signIn, respondToChallenge, signOut, hasRole,
      capabilities, hasFeature, mfaStatus, mfaResolved, refreshMfaStatus,
      sessionNotice, clearSessionNotice,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

const AUTH_FALLBACK: AuthContextType = {
  user: null,
  isLoading: true,
  isAuthenticated: false,
  // null = "not known". Outside a provider nothing is known, which is the
  // honest value here (ADR-377).
  mfaStatus: null,
  mfaResolved: false,
  sessionNotice: null,
  clearSessionNotice: () => {},
  refreshMfaStatus: async () => {},
  signIn: async () => { throw new Error('useAuth must be used inside AuthProvider'); },
  respondToChallenge: async () => { throw new Error('useAuth must be used inside AuthProvider'); },
  signOut: async () => {},
  hasRole: () => false,
  capabilities: null,
  hasFeature: () => true,
};

export function useAuth() {
  return useContext(AuthContext) ?? AUTH_FALLBACK;
}

// ── helpers ───────────────────────────────────────────────────────────────────

async function storeTokens(tokens: {
  AccessToken: string;
  IdToken: string;
  /** Absent for an Amplify-driven sign-in: Amplify keeps the refresh token in
   *  its own storage and does not expose it. tokenRefresh falls back to
   *  fetchAuthSession when this key is missing. */
  RefreshToken?: string;
}) {
  await AsyncStorage.setItem('asheflow_access_token',  tokens.AccessToken);
  await AsyncStorage.setItem('asheflow_id_token',      tokens.IdToken);
  if (tokens.RefreshToken) {
    await AsyncStorage.setItem('asheflow_refresh_token', tokens.RefreshToken);
  }
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
