export type CrmActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialCrmActionState: CrmActionState = { status: "idle" };
