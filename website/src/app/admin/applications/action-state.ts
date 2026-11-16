export type ApplicationActionState = {
  status: "idle" | "success" | "error";
  message?: string;
  activationUrl?: string;
  updateUrl?: string;
  emailStatus?: string;
};

export const initialApplicationActionState: ApplicationActionState = {
  status: "idle",
};
