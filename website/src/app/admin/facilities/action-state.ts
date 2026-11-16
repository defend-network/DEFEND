export type FacilityActionState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialFacilityActionState: FacilityActionState = { status: "idle" };
