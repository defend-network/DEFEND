export type NewsletterState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialNewsletterState: NewsletterState = { status: "idle" };
