import { groupKey, otpauthUri, rawKey } from '../setupKeyFormat';

const KEY = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP';

describe('the setup key (ADR-557)', () => {
  it('builds the standard otpauth URI an authenticator can open', () => {
    expect(otpauthUri(KEY, 'test.surveyor')).toBe(
      `otpauth://totp/AsheFlow%3Atest.surveyor?secret=${KEY}&issuer=AsheFlow`,
    );
  });

  it('never puts the display spacing into the URI or the clipboard', () => {
    const grouped = groupKey(KEY);
    expect(grouped).toBe('JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP');
    expect(rawKey(grouped)).toBe(KEY);
    expect(otpauthUri(grouped, 'a')).toContain(`secret=${KEY}&`);
  });

  it('escapes an account name that would break the label', () => {
    expect(otpauthUri(KEY, 'a b:c')).toContain('otpauth://totp/AsheFlow%3Aa%20b%3Ac?');
  });

  it('still produces a label with no account', () => {
    expect(otpauthUri(KEY, '')).toContain('AsheFlow%3Aaccount?');
  });
});
