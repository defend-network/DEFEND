export type ProgramActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialProgramActionState: ProgramActionState = { status: "idle" };
