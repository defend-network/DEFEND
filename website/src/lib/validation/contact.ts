import { z } from "zod";

export const contactSchema = z.object({
  name: z.string().trim().min(2, "Enter your name.").max(120),
  email: z.string().trim().email("Enter a valid email address.").max(320),
  subject: z.string().trim().min(3, "Enter a subject.").max(160),
  message: z
    .string()
    .trim()
    .min(10, "Enter a message of at least 10 characters.")
    .max(4000, "Keep the message under 4,000 characters."),
});

export type ContactInput = z.infer<typeof contactSchema>;
