/** Amplify configuration for the mobile app (ADR-362 phase 2).
 *
 *  Mobile talked to Cognito with hand-rolled fetch calls against InitiateAuth.
 *  That was fine while sign-in was one round trip, and stopped being fine with
 *  device tracking: a REMEMBERED device does not return tokens, it returns a
 *  `DEVICE_SRP_AUTH` challenge, and answering it needs a full SRP-6a handshake
 *  (3072-bit modexp, HKDF, HMAC over the device secret).
 *
 *  Writing that by hand means owning security-critical crypto in JS where a
 *  subtle bug either fails open or locks every field user out. Amplify already
 *  implements it (`handleDeviceSRPAuth`), the web client already depends on it,
 *  and using it here means one protocol implementation instead of two that
 *  drift.
 *
 *  Imported for its side effect from index.js, BEFORE the app renders — an auth
 *  call against an unconfigured Amplify throws.
 */
import { Amplify } from 'aws-amplify';
import { cognitoUserPoolsTokenProvider } from 'aws-amplify/auth/cognito';
import { defaultStorage } from 'aws-amplify/utils';
import { COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, COGNITO_OAUTH_DOMAIN, COGNITO_REDIRECT_URI } from '@env';

const REDIRECT = COGNITO_REDIRECT_URI ?? 'asheflow://callback';

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: COGNITO_USER_POOL_ID ?? '',
      userPoolClientId: COGNITO_CLIENT_ID ?? '',
      loginWith: {
        username: true,
        oauth: {
          domain: COGNITO_OAUTH_DOMAIN ?? '',
          scopes: ['email', 'openid', 'profile'],
          redirectSignIn: [REDIRECT],
          redirectSignOut: [REDIRECT],
          responseType: 'code',
        },
      },
    },
  },
});

// AsyncStorage-backed, so a session survives an app restart the way the
// hand-rolled storeTokens() did.
cognitoUserPoolsTokenProvider.setKeyValueStorage(defaultStorage);
