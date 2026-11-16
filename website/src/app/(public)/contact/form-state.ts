export type ContactFormState = {
  status: "idle" | "success" | "error";
  message?: string;
  fieldErrors?: Record<string, string>;
};

export const initialContactState: ContactFormState = { status: "idle" };
