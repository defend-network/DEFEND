export function isSessionMfaVerified(
  verifiedAt: Date | null | undefined,
): boolean {
  return verifiedAt instanceof Date && !Number.isNaN(verifiedAt.getTime());
}
