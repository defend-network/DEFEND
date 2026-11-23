import { describe, expect, it } from "vitest";

import {
  RELEASE_STATES,
  isPubliclyActivated,
  isReleaseState,
  releaseStateAtLeast,
} from "./releases";

describe("feature release registry", () => {
  it("defines the seven approved release states", () => {
    expect(RELEASE_STATES).toHaveLength(7);
    expect(RELEASE_STATES).toEqual([
      "implemented",
      "tested",
      "staging_validated",
      "owner_reviewed",
      "deployed",
      "legally_authorized",
      "publicly_activated",
    ]);
  });

  it("does not treat deployment as public activation", () => {
    expect(isPubliclyActivated("deployed")).toBe(false);
    expect(isPubliclyActivated("legally_authorized")).toBe(false);
    expect(isPubliclyActivated("publicly_activated")).toBe(true);
  });

  it("orders release states", () => {
    expect(releaseStateAtLeast("staging_validated", "tested")).toBe(true);
    expect(releaseStateAtLeast("implemented", "tested")).toBe(false);
    expect(releaseStateAtLeast("publicly_activated", "legally_authorized")).toBe(
      true,
    );
    expect(releaseStateAtLeast("unknown", "implemented")).toBe(false);
  });

  it("validates release state strings", () => {
    expect(isReleaseState("deployed")).toBe(true);
    expect(isReleaseState("live")).toBe(false);
  });
});
