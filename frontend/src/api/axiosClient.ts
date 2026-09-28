import axios from 'axios';
import { fetchAuthSession, signOut } from 'aws-amplify/auth';

if (!import.meta.env.VITE_API_URL) {
  throw new Error('VITE_API_URL is not set. Add it to .env.local (dev) or the CI secrets (staging/prod).');
}
const BASE_URL = import.meta.env.VITE_API_URL;

const axiosClient = axios.create({
  baseURL: BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

axiosClient.interceptors.request.use(
  async (config) => {
    try {
      const session = await fetchAuthSession();
      const token = session.tokens?.idToken?.toString();
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    } catch (error) {
      console.warn('Unable to get auth session for axios request', error);
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

axiosClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      // JWT expired or invalid — sign out and redirect to login so the user
      // gets a fresh token rather than seeing silent API failures.
      try {
        await signOut();
      } catch {
        // signOut itself failed (e.g. already signed out) — still redirect
      }
      window.location.href = '/login';
    }

    /* ADR-465 D3. The API refuses a blocked caller with this code, and the
       client must route on it -- otherwise a session that becomes blocked
       mid-flight (enrolment cleared elsewhere) shows silent failures instead of
       the wall.
       Routed on the CODE, never the message: string-matching an error text
       breaks the moment the copy is edited.
       Not signOut(): they are legitimately signed in and simply owe a factor.
       Signing them out would make the fix harder to reach, which is the
       opposite of the intent. */
    if (error.response?.status === 403
        && error.response?.data?.detail?.code === 'mfa_enrolment_required'
        && window.location.pathname !== '/mfa-setup') {
      window.location.assign('/mfa-setup');
    }
    return Promise.reject(error);
  }
);

export default axiosClient;
