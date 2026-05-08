import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { ThemeProvider } from './contexts/ThemeContext'

import { Amplify } from 'aws-amplify';

const _poolId    = import.meta.env.VITE_AWS_POOL_ID;
const _clientId  = import.meta.env.VITE_AWS_CLIENT_ID;
const _authDomain = import.meta.env.VITE_AWS_DOMAIN;

if (!_poolId || !_clientId || !_authDomain) {
  throw new Error(
    'Missing required Amplify env vars. Copy frontend/.env.template → frontend/.env.local and fill in values.'
  );
}

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: _poolId,
      userPoolClientId: _clientId,
      loginWith: {
        username: true,
        oauth: {
          domain: _authDomain,
          scopes: ['email', 'openid', 'profile'],
          redirectSignIn: [window.location.origin + '/'],
          redirectSignOut: [window.location.origin + '/login'],
          responseType: 'code'
        }
      }
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
