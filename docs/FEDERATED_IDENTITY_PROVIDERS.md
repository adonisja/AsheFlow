# Federated Identity Providers — DSP Test Company

These providers were configured and verified on the original Cognito pool
for the DSP test company. They must be re-wired into a new pool when one is created.

**Credentials are stored in `backend/.env` (gitignored) — not here.**

---

## Discord (OIDC)

| Setting | Value |
|---|---|
| Provider name | `Discord` |
| Provider type | OIDC |
| Authorize URL | `https://discord.com/api/oauth2/authorize` |
| Token URL | `https://discord.com/api/oauth2/token` |
| Attributes URL | `https://discord.com/api/users/@me` |
| JWKS URI | `https://discord.com/api/oauth2/keys` |
| OIDC issuer | `https://discord.com` |
| Authorize scopes | `openid email identify` |
| Attributes request method | `GET` |
| Attribute mapping | `email → email`, `username → sub` |
| Client ID | stored in `.env` |
| Client secret | stored in `.env` |

**Note on Discord OAuth app:** The Discord developer application behind this
provider needs its redirect URI updated to point at the new Cognito hosted UI
domain once the new pool is created. Old URI pattern:
`https://<old-domain>.auth.us-east-2.amazoncognito.com/oauth2/idpresponse`

---

## Google (OAuth2)

| Setting | Value |
|---|---|
| Provider name | `Google` |
| Provider type | Google |
| Authorize URL | `https://accounts.google.com/o/oauth2/v2/auth` |
| Token URL | `https://www.googleapis.com/oauth2/v4/token` |
| Attributes URL | `https://people.googleapis.com/v1/people/me?personFields=` |
| Authorize scopes | `profile email openid` |
| Token request method | `POST` |
| Attribute mapping | `email → email`, `username → sub` |
| Client ID | stored in `.env` |
| Client secret | stored in `.env` |

**Note on Google OAuth app:** The Google Cloud Console OAuth client needs its
authorized redirect URI updated to the new Cognito hosted UI domain once the
new pool is created. Old URI pattern:
`https://<old-domain>.auth.us-east-2.amazoncognito.com/oauth2/idpresponse`

---

## Re-wiring checklist

- [x] Create Discord OIDC provider on new pool using credentials from `.env`
- [x] Update Discord developer app redirect URI to new Cognito domain
- [x] Create Google provider on new pool using credentials from `.env`
- [x] Update Google Cloud Console OAuth client redirect URI to new Cognito domain
- [x] Add both providers to the new app client's `SupportedIdentityProviders`
- [ ] Test Discord sign-in flow end to end
- [ ] Test Google sign-in flow end to end

## New pool hosted UI domain

```
https://asheflow-auth.auth.us-east-2.amazoncognito.com
```

IdP response URL (registered in Discord + Google):
```
https://asheflow-auth.auth.us-east-2.amazoncognito.com/oauth2/idpresponse
```
