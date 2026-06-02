import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import { ASHEFLOW_API_URL, ASHEFLOW_LAN_IP } from '@env';

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

// Attach the Cognito JWT on every request, same pattern as the web axiosClient
apiClient.interceptors.request.use(async config => {
  const token = await AsyncStorage.getItem('asheflow_id_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On 401, clear stored tokens so the app forces re-login
apiClient.interceptors.response.use(
  res => res,
  async err => {
    if (err.response?.status === 401) {
      await AsyncStorage.multiRemove([
        'asheflow_access_token',
        'asheflow_id_token',
        'asheflow_refresh_token',
      ]);
    }
    return Promise.reject(err);
  },
);

export default apiClient;
