export type EventActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialEventActionState: EventActionState = { status: "idle" };
