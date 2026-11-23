import { z } from "zod";

export const PAID_TIER_KEYS = ["standard", "supporter", "patron"] as const;

export const applicationSchema = z.object({
  legalName: z.string().trim().min(2, "Enter your legal name.").max(160),
  preferredName: z.string().trim().max(80).optional(),
  email: z.string().trim().email("Enter a valid email address.").max(320),
  phone: z.string().trim().max(40).optional(),
  city: z.string().trim().min(2, "Enter your city.").max(120),
  state: z.string().trim().length(2, "Use the two-letter state code."),
  postalCode: z.string().trim().max(20).optional(),
  desiredChapterId: z
    .string()
    .trim()
    .min(1, "Select an operating chapter.")
    .max(100),
  requestedTier: z.enum(PAID_TIER_KEYS),
  interests: z.array(z.string().trim().max(80)).max(20),
  skills: z.string().trim().max(1000).optional(),
  volunteerInterests: z.array(z.string().trim().max(80)).max(20),
  programInterests: z.array(z.string().trim().max(80)).max(20),
  policiesAccepted: z
    .string()
    .refine(
      (value) => value === "on",
      "You must accept the membership policies.",
    ),
  privacyAcknowledged: z
    .string()
    .refine(
      (value) => value === "on",
      "You must acknowledge the privacy notice.",
    ),
  adultConfirmed: z
    .string()
    .refine(
      (value) => value === "on",
      "You must confirm that you are 18 or older.",
    ),
});

export type ApplicationInput = z.infer<typeof applicationSchema>;

export function validationFieldErrors(error: z.ZodError): Record<string, string> {
  const result: Record<string, string> = {};
  for (const issue of error.issues) {
    const key = String(issue.path[0] ?? "form");
    result[key] ??= issue.message;
  }
  return result;
}
