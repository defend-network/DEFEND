export type MemberActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialMemberActionState: MemberActionState = { status: "idle" };
