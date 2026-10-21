/** Pure formatting for the setup key (ADR-557), apart from the component so
 *  it can be unit-tested without the native clipboard module. */

const ISSUER = 'AsheFlow';

/** The key with any spacing removed: what goes on the clipboard and in the URI. */
export function rawKey(secret: string): string {
  return secret.replace(/\s+/g, '');
}

/** Google's Key Uri Format: otpauth://totp/Issuer:account?secret=...&issuer=Issuer.
 *  Every mainstream authenticator registers otpauth:// and reads this. */
export function otpauthUri(secret: string, account: string): string {
  const label = encodeURIComponent(`${ISSUER}:${account || 'account'}`);
  return `otpauth://totp/${label}?secret=${encodeURIComponent(rawKey(secret))}&issuer=${ISSUER}`;
}

/** Shown in groups of four for reading and checking; never copied this way. */
export function groupKey(secret: string): string {
  return rawKey(secret).replace(/(.{4})(?=.)/g, '$1 ');
}
