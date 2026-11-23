export type MfaSessionState = {
  twoFactorEnabled: boolean;
  twoFactorEnabledAt: Date | null;
  sessionCreatedAt: Date;
};

export function isMfaSessionVerified(input: MfaSessionState): boolean {
  if (!input.twoFactorEnabled) return false;
  if (!input.twoFactorEnabledAt) return false;
  return (
    input.sessionCreatedAt.getTime() >= input.twoFactorEnabledAt.getTime()
  );
}
