/**
 * Register this device for push, and revoke it on sign-out (ADR-487 D5).
 *
 * ANDROID ONLY FOR NOW, and deliberately so. iOS needs the raw APNs device
 * token (the backend's SNS APNS platform application cannot use an FCM token),
 * and the Apple Developer Program step that unlocks APNs is parked. On iOS
 * every function here is a no-op — see react-native.config.js, which links
 * React Native Firebase on Android only.
 *
 * PUSH IS ADDITIVE. Every notification still arrives in-app. So every failure
 * here — permission denied, Firebase not configured (no google-services.json
 * yet), the network, the API — is swallowed and logged in dev. Nothing in this
 * module may block sign-in or sign-out.
 */
import { PermissionsAndroid, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import apiClient from '@api/client';

/** The token we last registered, so sign-out can revoke the same one. */
const TOKEN_KEY = 'asheflow_push_token';

/**
 * The three calls this module makes, bound to one Messaging instance.
 *
 * MODULAR API ONLY. React Native Firebase v26 removed the namespaced default
 * export, so `require(...).default()` is undefined and calling the module
 * object throws. The first version of this file did exactly that: the throw
 * was swallowed, `messaging()` returned null, and registration exited before
 * the permission prompt, so push was silently off on every Android device.
 * test_adr487_d5_mobile_push.py pins the modular names against the installed
 * package so a future major cannot repeat it.
 */
type Messaging = {
  getToken(): Promise<string>;
  onTokenRefresh(listener: (token: string) => void): () => void;
};

/**
 * Firebase Messaging, required LAZILY and only on Android.
 *
 * A top-level import would execute on iOS too, where the native module is not
 * linked, and could throw at module load — taking the whole app down over an
 * optional feature. Requiring it inside this guard means iOS never evaluates
 * the package at all.
 */
function messaging(): Messaging | null {
  if (Platform.OS !== 'android') return null;
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { getMessaging, getToken, onTokenRefresh } = require('@react-native-firebase/messaging');
    const instance = getMessaging();
    return {
      getToken: () => getToken(instance),
      onTokenRefresh: (listener: (token: string) => void) => onTokenRefresh(instance, listener),
    };
  } catch (e) {
    // Logged, not just swallowed: this catch hid a removed API for a release.
    if (__DEV__) console.warn('[push] messaging unavailable:', (e as Error)?.message);
    return null;
  }
}

/**
 * Android 13+ shows nothing without a runtime grant (targetSdk 36). Older
 * versions grant notifications at install, so there is nothing to ask.
 *
 * Asked once per launch at most, and only after sign-in: a permission dialog
 * on the login screen is a dialog with no context, and the usual answer to
 * that is "Don't allow" — which Android then remembers.
 */
async function ensurePermission(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  if (typeof Platform.Version === 'number' && Platform.Version < 33) return true;
  try {
    const result = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
    );
    return result === PermissionsAndroid.RESULTS.GRANTED;
  } catch {
    return false;
  }
}

async function postToken(token: string): Promise<void> {
  await apiClient.post('/notifications/devices', { platform: 'android', token });
  await AsyncStorage.setItem(TOKEN_KEY, token);
}

/**
 * Register for push. Returns an unsubscribe for the token-refresh listener.
 *
 * Re-registering every launch is intended: the backend treats a known token as
 * a refresh (and MOVES it if it now belongs to someone else), so this is
 * idempotent and also repairs a token that rotated while the app was closed.
 */
export async function registerForPush(): Promise<() => void> {
  const noop = () => {};
  const m = messaging();
  if (!m) return noop;

  if (!(await ensurePermission())) return noop;

  try {
    const token = await m.getToken();
    if (token) await postToken(token);
  } catch (e) {
    // Most likely: no google-services.json, so Firebase is uninitialised.
    if (__DEV__) console.warn('[push] registration skipped:', (e as Error)?.message);
    return noop;
  }

  // FCM rotates tokens. Without this, a rotation leaves the backend sending to
  // a dead token until SNS reports the endpoint disabled.
  try {
    return m.onTokenRefresh(token => {
      postToken(token).catch(() => {});
    });
  } catch {
    return noop;
  }
}

/**
 * Revoke this device. Call BEFORE the session tokens are cleared — the DELETE
 * is authenticated, so afterwards it would 401 and the device would keep
 * receiving the previous user's notifications.
 */
export async function unregisterFromPush(): Promise<void> {
  if (Platform.OS !== 'android') return;
  try {
    const token = await AsyncStorage.getItem(TOKEN_KEY);
    if (!token) return;
    await apiClient.delete('/notifications/devices', {
      data: { platform: 'android', token },
    });
    await AsyncStorage.removeItem(TOKEN_KEY);
  } catch {
    // Best effort. If this fails, the backend still stops delivering once the
    // next user signs in on this phone: registration MOVES the token.
  }
}
