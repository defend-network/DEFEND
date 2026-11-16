export type VolunteerRegistrationState = {
  status: "idle" | "success" | "error";
  message?: string;
};

export const initialVolunteerRegistrationState: VolunteerRegistrationState = {
  status: "idle",
};
