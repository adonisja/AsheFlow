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
    return Promise.reject(error);
  }
);

export default axiosClient;
