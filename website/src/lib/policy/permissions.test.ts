import { describe, expect, it } from "vitest";

import {
  type ActorContext,
  can,
  canAccessChapter,
  canAccessModule,
  scopedChapterIds,
} from "@/lib/policy/permissions";

function actor(overrides: Partial<ActorContext> = {}): ActorContext {
  return {
    userId: "user_1",
    displayName: "Test User",
    email: "test@example.com",
    roles: [{ roleKey: "member", scopeType: "self", scopeId: null }],
    mfaVerified: false,
    ...overrides,
  };
}

describe("central authorization policy", () => {
  it("does not authorize anonymous users", () => {
    expect(can(null, "applications.view")).toBe(false);
  });

  it("does not grant administrative permissions to members", () => {
    expect(can(actor(), "applications.view")).toBe(false);
    expect(can(actor(), "members.manage")).toBe(false);
  });

  it("grants global owner permissions after MFA", () => {
    const owner = actor({
      roles: [{ roleKey: "owner", scopeType: "global", scopeId: null }],
      mfaVerified: true,
    });
    expect(can(owner, "applications.review")).toBe(true);
    expect(can(owner, "system.users")).toBe(true);
    expect(can(owner, "finance.manage")).toBe(true);
    expect(scopedChapterIds(owner)).toBe("all");
  });

  it("fails closed for MFA-required actions when MFA is not verified", () => {
    const owner = actor({
      roles: [{ roleKey: "owner", scopeType: "global", scopeId: null }],
      mfaVerified: false,
    });
    expect(can(owner, "members.manage")).toBe(false);
    expect(can(owner, "applications.view")).toBe(true);
  });

  it("scopes chapter administrators to their chapter", () => {
    const chapterAdmin = actor({
      roles: [
        {
          roleKey: "chapter_admin",
          scopeType: "chapter",
          scopeId: "chapter_pasco",
        },
      ],
      mfaVerified: true,
    });
    expect(
      can(chapterAdmin, "applications.view", { chapterId: "chapter_pasco" }),
    ).toBe(true);
    expect(
      can(chapterAdmin, "applications.view", { chapterId: "chapter_orlando" }),
    ).toBe(false);
    expect(can(chapterAdmin, "applications.view")).toBe(false);
    expect(canAccessChapter(chapterAdmin, "chapter_pasco")).toBe(true);
    expect(canAccessChapter(chapterAdmin, "chapter_orlando")).toBe(false);
    expect(scopedChapterIds(chapterAdmin)).toEqual(["chapter_pasco"]);
  });

  it("does not let chapter administrators manage system settings or global modules", () => {
    const chapterAdmin = actor({
      roles: [
        {
          roleKey: "chapter_admin",
          scopeType: "chapter",
          scopeId: "chapter_pasco",
        },
      ],
      mfaVerified: true,
    });
    expect(can(chapterAdmin, "system.settings")).toBe(false);
    expect(can(chapterAdmin, "members.roles")).toBe(false);
    expect(canAccessModule(chapterAdmin, "crm.view")).toBe(false);
    expect(canAccessModule(chapterAdmin, "finance.view")).toBe(false);
    expect(canAccessModule(chapterAdmin, "cms.edit")).toBe(false);
    expect(canAccessModule(chapterAdmin, "communications.view")).toBe(false);
  });

  it("grants national administrators global operational access but not owner-only settings", () => {
    const national = actor({
      roles: [
        { roleKey: "national_admin", scopeType: "global", scopeId: null },
      ],
      mfaVerified: true,
    });
    expect(can(national, "finance.manage")).toBe(true);
    expect(can(national, "system.audit")).toBe(true);
    expect(can(national, "system.users")).toBe(false);
  });
});
