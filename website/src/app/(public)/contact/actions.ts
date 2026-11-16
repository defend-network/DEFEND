"use server";

import { getDb } from "@/lib/db/client";
import { contactSchema } from "@/lib/validation/contact";
import { validationFieldErrors } from "@/lib/validation/application";
import { contactMessages } from "@/db/schema";
import type { ContactFormState } from "./form-state";

export async function submitContact(
  _previous: ContactFormState,
  formData: FormData,
): Promise<ContactFormState> {
  const honeypot = String(formData.get("website") ?? "");
  if (honeypot.trim()) {
    return {
      status: "success",
      message: "Thank you. Your message has been received.",
    };
  }

  const parsed = contactSchema.safeParse({
    name: formData.get("name"),
    email: formData.get("email"),
    subject: formData.get("subject"),
    message: formData.get("message"),
  });

  if (!parsed.success) {
    return {
      status: "error",
      message: "Please correct the highlighted fields.",
      fieldErrors: validationFieldErrors(parsed.error),
    };
  }

  try {
    const db = await getDb();
    await db.insert(contactMessages).values({
      id: `contact_${crypto.randomUUID()}`,
      name: parsed.data.name,
      email: parsed.data.email.toLowerCase(),
      subject: parsed.data.subject,
      message: parsed.data.message,
      status: "new",
      createdAt: new Date(),
    });
    return {
      status: "success",
      message:
        "Thank you. Your message has been received and will be reviewed by an administrator.",
    };
  } catch {
    return {
      status: "error",
      message:
        "We could not save your message. Please try again or email us directly.",
    };
  }
}
