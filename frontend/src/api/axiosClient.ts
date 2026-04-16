import axios from 'axios';
import { fetchAuthSession, signOut } from 'aws-amplify/auth';

// VITE_API_URL must be set in .env (development) and in the build environment
// (staging/production). Falls back to localhost only as a last resort so a
// missing env var produces an obvious failure rather than a silent wrong-host request.
const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1';

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
