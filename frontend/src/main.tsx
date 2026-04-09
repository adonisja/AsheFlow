import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

import { Amplify } from 'aws-amplify';

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_AWS_POOL_ID || 'us-east-2_xxxxxxxxx',
      userPoolClientId: import.meta.env.VITE_AWS_CLIENT_ID || 'xxxxxxxxxxxxxxxxx',
      loginWith: {
        email: true,
        oauth: {
          domain: import.meta.env.VITE_AWS_DOMAIN || 'asheflow.auth.us-east-2.amazoncognito.com',
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
    <App />
  </StrictMode>,
)
