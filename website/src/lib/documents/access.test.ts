import { describe, expect, it } from "vitest";

import {
  type ActorContext,
  canAccessModule,
  chapterIdsForPermission,
  hasAnyAdminPermission,
} from "@/lib/policy/permissions";
import { canReadDocument, canManageDocument } from "./documents";

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

const owner = actor({
  roles: [{ roleKey: "owner", scopeType: "global", scopeId: null }],
  mfaVerified: true,
});
const staff = actor({
  roles: [{ roleKey: "staff", scopeType: "global", scopeId: null }],
  mfaVerified: true,
});
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

describe("admin access helpers", () => {
  it("recognizes administrative roles", () => {
    expect(hasAnyAdminPermission(owner)).toBe(true);
    expect(hasAnyAdminPermission(staff)).toBe(true);
    expect(hasAnyAdminPermission(chapterAdmin)).toBe(true);
    expect(hasAnyAdminPermission(actor())).toBe(false);
  });

  it("derives chapter filters from the permission", () => {
    expect(chapterIdsForPermission(owner, "applications.view")).toBe("all");
    expect(chapterIdsForPermission(chapterAdmin, "applications.view")).toEqual([
      "chapter_pasco",
    ]);
    expect(chapterIdsForPermission(actor(), "applications.view")).toEqual([]);
  });

  it("allows chapter administrators to open their module pages", () => {
    expect(canAccessModule(chapterAdmin, "applications.view")).toBe(true);
    expect(canAccessModule(chapterAdmin, "documents.view")).toBe(true);
    expect(canAccessModule(chapterAdmin, "system.users")).toBe(false);
    expect(canAccessModule(staff, "members.view")).toBe(true);
    expect(canAccessModule(actor(), "members.view")).toBe(false);
  });
});

describe("document access", () => {
  it("allows owners to read and manage sensitive documents", () => {
    const document = {
      status: "published",
      visibility: "admin",
      chapterId: null,
    };
    expect(canReadDocument(owner, document)).toBe(true);
    expect(canManageDocument(owner, document)).toBe(true);
  });

  it("does not let staff read or modify admin-only documents", () => {
    const document = {
      status: "published",
      visibility: "admin",
      chapterId: null,
    };
    expect(canReadDocument(staff, document)).toBe(false);
    expect(canManageDocument(staff, document)).toBe(false);
  });

  it("scopes chapter documents to the matching chapter", () => {
    const pasco = {
      status: "published",
      visibility: "chapter",
      chapterId: "chapter_pasco",
    };
    const orlando = {
      status: "published",
      visibility: "chapter",
      chapterId: "chapter_orlando",
    };
    expect(canReadDocument(chapterAdmin, pasco)).toBe(true);
    expect(canManageDocument(chapterAdmin, pasco)).toBe(true);
    expect(canReadDocument(chapterAdmin, orlando)).toBe(false);
    expect(canManageDocument(chapterAdmin, orlando)).toBe(false);
  });

  it("does not expose archived documents", () => {
    const document = {
      status: "archived",
      visibility: "members",
      chapterId: "chapter_pasco",
    };
    expect(canReadDocument(owner, document)).toBe(false);
    expect(canReadDocument(chapterAdmin, document)).toBe(false);
  });

  it("does not grant document access to members", () => {
    const document = {
      status: "published",
      visibility: "members",
      chapterId: "chapter_pasco",
    };
    expect(canReadDocument(actor(), document)).toBe(false);
    expect(canManageDocument(actor(), document)).toBe(false);
  });
});
