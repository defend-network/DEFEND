import { describe, expect, it } from "vitest";

import {
  applicationSchema,
  validationFieldErrors,
} from "@/lib/validation/application";
import { contactSchema } from "@/lib/validation/contact";

const validApplication = {
  legalName: "Test Applicant",
  preferredName: "Test",
  email: "test@example.com",
  phone: "555-0100",
  city: "New Port Richey",
  state: "FL",
  postalCode: "34652",
  desiredChapterId: "chapter_pasco",
  interests: ["Cultural heritage"],
  skills: "Carpentry",
  volunteerInterests: ["Events"],
  programInterests: ["Mentorship"],
  policiesAccepted: "on",
  privacyAcknowledged: "on",
};

describe("application validation", () => {
  it("accepts a complete application for the operating chapter", () => {
    expect(applicationSchema.safeParse(validApplication).success).toBe(true);
  });

  it("rejects planned chapters and missing acknowledgements", () => {
    const result = applicationSchema.safeParse({
      ...validApplication,
      desiredChapterId: "chapter_orlando",
      policiesAccepted: "",
      privacyAcknowledged: "",
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      const errors = validationFieldErrors(result.error);
      expect(errors.desiredChapterId).toMatch(/operating chapter/i);
      expect(errors.policiesAccepted).toMatch(/membership policies/i);
      expect(errors.privacyAcknowledged).toMatch(/privacy notice/i);
    }
  });

  it("rejects malformed email and oversized arrays", () => {
    const result = applicationSchema.safeParse({
      ...validApplication,
      email: "not-an-email",
      interests: Array.from({ length: 21 }, () => "x"),
    });
    expect(result.success).toBe(false);
  });
});

describe("contact validation", () => {
  it("accepts a reasonable message", () => {
    expect(
      contactSchema.safeParse({
        name: "Test Person",
        email: "test@example.com",
        subject: "Question",
        message: "This is a reasonable message body.",
      }).success,
    ).toBe(true);
  });

  it("rejects a short message", () => {
    expect(
      contactSchema.safeParse({
        name: "Test Person",
        email: "test@example.com",
        subject: "Question",
        message: "short",
      }).success,
    ).toBe(false);
  });
});
