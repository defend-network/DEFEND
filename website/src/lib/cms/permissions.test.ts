import { describe, expect, it } from "vitest";

import { cmsWritePermission } from "./permissions";

describe("CMS write permissions", () => {
  it("requires publish permission for published content", () => {
    expect(cmsWritePermission({ publish: true })).toBe("cms.publish");
    expect(cmsWritePermission({ publish: true, visibility: "admin" })).toBe(
      "cms.publish",
    );
  });

  it("requires publish permission for member or public announcements", () => {
    expect(cmsWritePermission({ visibility: "members" })).toBe("cms.publish");
    expect(cmsWritePermission({ visibility: "public" })).toBe("cms.publish");
  });

  it("allows draft or admin-only content with edit permission", () => {
    expect(cmsWritePermission({ visibility: "admin" })).toBe("cms.edit");
    expect(cmsWritePermission({})).toBe("cms.edit");
  });
});
