import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { BackgroundCheckPanel } from "../BackgroundCheckPanel";

it("shows the approved screening actions as future controls", () => {
  render(<BackgroundCheckPanel />);

  for (const name of [
    "New background check",
    "Person search",
    "Business search",
    "Court records",
    "Sanctions / watchlists",
    "Web research",
    "Social media search",
    "Voter status",
    "Saved cases",
    "Generate report",
  ]) {
    expect(screen.getByRole("button", { name })).toBeDisabled();
  }
  expect(screen.getByText(/canonical person record/i)).toBeVisible();
  expect(screen.getByText("Evidence for human review")).toBeVisible();
});
