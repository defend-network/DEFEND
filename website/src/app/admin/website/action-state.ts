export type CmsActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialCmsActionState: CmsActionState = { status: "idle" };
