import axios from 'axios';
import { Platform } from 'react-native';
import { ASHEFLOW_API_URL, ASHEFLOW_LAN_IP } from '@env';
import { clearTokens, getValidIdToken, touchLastActive } from './tokenRefresh';

/* ADR-541 D2. Another device changed this account's password or email, so the
   server ended this session on purpose. A silent refresh cannot fix that (the
   refresh token is revoked, and a still-fresh ID token would just 401 again),
   so the tokens are cleared and AuthContext is told, so the person sees WHY.
   Routed on the code, never the text (ADR-465 D3). */
type Listener = () => void;
const credentialsChangedListeners = new Set<Listener>();
export function onCredentialsChanged(fn: Listener): () => void {
  credentialsChangedListeners.add(fn);
  return () => { credentialsChangedListeners.delete(fn); };
}

function resolveBaseUrl(): string {
  // Explicit override wins (e.g. staging/prod URL set in .env)
  if (ASHEFLOW_API_URL) return ASHEFLOW_API_URL;

  const lan = ASHEFLOW_LAN_IP ?? '192.168.1.1';
  const port = '8000';

  // Android emulator reaches the host machine via 10.0.2.2
  // iOS simulator shares the host network, so localhost works directly
  // Physical devices must use the host's LAN IP
  if (Platform.OS === 'android') return `http://10.0.2.2:${port}/api/v1`;
  return `http://${lan}:${port}/api/v1`;
}

const BASE_URL = resolveBaseUrl();

const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
    'ngrok-skip-browser-warning': 'true',
  },
});

// Attach a VALID Cognito JWT on every request — getValidIdToken silently
// refreshes via the Cognito refresh token when the 1-hour ID token is stale,
// and enforces the inactivity window (tokenRefresh.ts).
apiClient.interceptors.request.use(async config => {
  const token = await getValidIdToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 401 → try ONE silent refresh + retry; only a failed refresh forces re-login
// (clearing the refresh token on every 401 is what broke auth persistence).
apiClient.interceptors.response.use(
  async res => {
    touchLastActive();   // successful traffic keeps the inactivity window open
    return res;
  },
  async err => {
    const original = err.config;
    if (err.response?.status === 401 && err.response?.data?.detail?.code === 'credentials_changed') {
      await clearTokens();
      credentialsChangedListeners.forEach(fn => fn());
      return Promise.reject(err);
    }
    if (err.response?.status === 401 && original && !original._retried) {
      original._retried = true;
      const token = await getValidIdToken();
      if (token) {
        original.headers.Authorization = `Bearer ${token}`;
        return apiClient(original);
      }
      // getValidIdToken cleared the tokens (refresh failed / window lapsed) —
      // the app's auth state will force re-login on next restore.
    }
    return Promise.reject(err);
  },
);

export default apiClient;
