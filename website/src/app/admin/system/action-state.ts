export type SystemActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialSystemActionState: SystemActionState = { status: "idle" };
