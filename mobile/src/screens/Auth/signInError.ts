/** What a failed sign-in should show (ADR-548 D5).
 *
 *  A Cognito trigger that refuses a sign-in reaches the client as
 *  "PreAuthentication failed with error <our sentence>". The wrapper is AWS's
 *  and cannot be changed at the source, so it is recognised and removed here.
 *  The two-factor refusal (enrolment window closed) is not an error the person
 *  made, and it has exactly one way out, so it gets a designed panel instead of
 *  red text.
 *
 *  Kept in step with its twin in the other client (web: utils/signInError.ts,
 *  mobile: screens/Auth/signInError.ts); a backend test compares the two.
 */
const TRIGGER_WRAPPER = /^(Pre|Post)Authentication failed with error\s*/i;

export type SignInProblem =
  | { kind: 'mfa_setup_closed' }
  | { kind: 'message'; text: string };

export function classifySignInError(raw: string | null | undefined, fallback: string): SignInProblem {
  const text = (raw ?? '').replace(TRIGGER_WRAPPER, '').trim();
  // Matches the current sentence and the pre-ADR-548 one, so a deploy in
  // either order still renders the panel.
  if (/two-factor/i.test(text) && /administrator/i.test(text)) {
    return { kind: 'mfa_setup_closed' };
  }
  return { kind: 'message', text: text || fallback };
}
