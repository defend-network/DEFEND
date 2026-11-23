export type FreeRegistrationState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialFreeRegistrationState: FreeRegistrationState = {
  status: "idle",
};
