export type MfaRecoveryState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialMfaRecoveryState: MfaRecoveryState = { status: "idle" };
