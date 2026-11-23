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
  requestedTier: "standard",
  interests: ["Cultural heritage"],
  skills: "Carpentry",
  volunteerInterests: ["Events"],
  programInterests: ["Mentorship"],
  policiesAccepted: "on",
  privacyAcknowledged: "on",
  adultConfirmed: "on",
};

describe("application validation", () => {
  it("accepts a complete application for the operating chapter", () => {
    expect(applicationSchema.safeParse(validApplication).success).toBe(true);
  });

  it("rejects missing acknowledgements", () => {
    const result = applicationSchema.safeParse({
      ...validApplication,
      policiesAccepted: "",
      privacyAcknowledged: "",
      adultConfirmed: "",
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      const errors = validationFieldErrors(result.error);
      expect(errors.policiesAccepted).toMatch(/membership policies/i);
      expect(errors.privacyAcknowledged).toMatch(/privacy notice/i);
      expect(errors.adultConfirmed).toMatch(/18 or older/i);
    }
  });

  it("requires a chapter and a paid tier", () => {
    expect(
      applicationSchema.safeParse({
        ...validApplication,
        desiredChapterId: "",
      }).success,
    ).toBe(false);
    expect(
      applicationSchema.safeParse({
        ...validApplication,
        requestedTier: "free",
      }).success,
    ).toBe(false);
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
