import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ThemeProvider } from './contexts/ThemeContext'

import { Amplify } from 'aws-amplify';

const _poolId    = import.meta.env.VITE_AWS_POOL_ID;
const _clientId  = import.meta.env.VITE_AWS_CLIENT_ID;

if (!_poolId || !_clientId) {
  throw new Error(
    'Missing required Amplify env vars. Copy frontend/.env.template → frontend/.env.local and fill in values.'
  );
}

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: _poolId,
      userPoolClientId: _clientId,
      // Username and password only (ADR-560): no OAuth / hosted UI, so no
      // Discord or Google redirect to configure.
      loginWith: { username: true }
    }
  }
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </StrictMode>,
)
