export type EventRegistrationState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialEventRegistrationState: EventRegistrationState = {
  status: "idle",
};
