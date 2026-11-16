export type DocumentActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialDocumentActionState: DocumentActionState = { status: "idle" };
