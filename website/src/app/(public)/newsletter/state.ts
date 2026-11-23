export type NewsletterState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialNewsletterState: NewsletterState = { status: "idle" };

export type UnsubscribeState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialUnsubscribeState: UnsubscribeState = { status: "idle" };
