import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { ASHEFLOW_API_URL } from '@env';

const BASE_URL = ASHEFLOW_API_URL ?? 'http://localhost:8000/api/v1';

const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' },
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
      await AsyncStorage.removeMany([
        'asheflow_access_token',
        'asheflow_id_token',
        'asheflow_refresh_token',
      ]);
    }
    return Promise.reject(err);
  },
);

export default apiClient;
