export type ApplicationFormState = {
  status: "idle" | "success" | "error";
  message?: string;
  applicationNumber?: string;
  fieldErrors?: Record<string, string>;
};

export const initialApplicationState: ApplicationFormState = { status: "idle" };
