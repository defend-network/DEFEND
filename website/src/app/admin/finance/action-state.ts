export type FinanceActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialFinanceActionState: FinanceActionState = { status: "idle" };
