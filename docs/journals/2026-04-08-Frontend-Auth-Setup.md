# Session Journal: Frontend Authentication Setup

**Date:** 2026-04-08
**Start Time:** 14:22 EDT
**End Time:** In Progress

## Session Goals
* Implement Phase 2 of `FRONTEND_PLAN.md`: Authentication layer
* Set up AWS Amplify with Cognito (User Pool & Federated SSO)
* Create a custom React Login Screen
* Implement Axios API Authorization interceptors

## Work Completed
1. **Frontend Dependencies:** Installed/configured `aws-amplify`, `@aws-amplify/auth`, `react-router-dom`, and missing `tslib`.
2. **AWS Amplify Initialization:** Hooked up `Amplify.configure()` in `src/main.tsx` pointing to Cognito. Polyfilled `window.global` in `index.html` to resolve an AWS Crypto Node.js dependency conflict in Vite.
3. **Custom UI:** Designed a responsive `Login.tsx` component with Tailwind CSS that bypasses AWS Hosted UI and offers Discord/Google SSO via `signInWithRedirect`.
4. **Vite + React Router:** Wrapped `App.tsx` with `react-router-dom` and created a `ProtectedRoute` to handle redirecting unauthenticated users safely to the login screen.
5. **Axios Integration:** Designed `axiosClient.ts` to automatically fetch `authSession()` and append the `Bearer {IdToken}` to all `http://localhost:8000/api/v1` API calls.
6. **Backend Enhancements:** Implemented FastAPI `CORSMiddleware` in `backend/app/main.py` allowing the Vite front-end to safely communicate with our `uvicorn` instance without being blocked by the browser. 
7. **Role Validation APIs:** Added `RoleChecker` dependencies to `employees.py` routes to enforce backend authorization.
8. **End-to-End Testing:** Placed a test API button in `Navbar.tsx` to verify successful end-to-end token flow.

## Key Learnings & Takeaways
* **Vite vs Webpack (Globals):** Modern bundlers like Vite do not inject Node.js globals (like `window.global = window`) into the browser context. This breaks legacy cryptographic libraries (like `@aws-crypto/sha256-js` used by Amplify). Injecting a manual polyfill inside `index.html` solves this gracefully.
* **IdTokens vs AccessTokens:** When using Cognito Federated SSO, the `cognito:groups` array is uniquely tied to the **IdToken**, not the AccessToken. Therefore, our API interceptor pulls the IdToken specifically to authorize the FastApi backend role checker. 
* **CORS Essentials:** Browsers strictly block cross-origin requests natively. The API must explicitly answer Preflight `OPTIONS` requests via `CORSMiddleware` allowing `localhost:3000` (or whichever port Vite runs on).

## Next Steps
* **Phase 4 (Starting Next):** Hook up the Worker Endpoints, including Profile, Preferences (Favorites/Bans), and Off Day submission forms.

## Technical Debt & Security Review (AWS Cognito)
* **Authentication Flows:** We encountered a `USER_SRP_AUTH is not enabled` error during local dev login. I temporarily downgraded Amplify's default `USER_SRP_AUTH` (Secure Remote Password) to `USER_PASSWORD_AUTH`. 
* **The "Why":** `USER_SRP_AUTH` is a zero-knowledge proof system where the password never leaves the browser (highly secure, Enterprise-grade). `USER_PASSWORD_AUTH` sends it over HTTPS (standard, but less secure). Our Sandbox App Client currently lacks the SRP flag.
* **Production Requirement:** Before production release, we must go to AWS Cognito Console, enable `ALLOW_USER_SRP_AUTH` on the App Client, and revert the `authFlowType` override inside `Login.tsx`.
