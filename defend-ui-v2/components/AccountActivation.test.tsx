import { StrictMode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import * as api from "@/lib/api";
import AccountActivation from "./AccountActivation";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { ...actual, activationStatus: vi.fn(), activateAccount: vi.fn() };
});

vi.mock("next/navigation", () => ({ useParams: () => ({}) }));

beforeEach(() => {
  vi.mocked(api.activationStatus).mockReset().mockResolvedValue({
    status: "pending",
    email: "member@example.com",
    display_name: "Member",
  });
  window.history.replaceState(null, "", "/activate");
});

it("captures the invitation from the URL fragment and immediately scrubs it", async () => {
  const token = "invite_fragment-only-secret";
  window.history.replaceState(null, "", `/activate#token=${encodeURIComponent(token)}`);

  render(<AccountActivation />);

  await waitFor(() => expect(api.activationStatus).toHaveBeenCalledWith(token));
  expect(window.location.pathname).toBe("/activate");
  expect(window.location.search).toBe("");
  expect(window.location.hash).toBe("");
  expect(await screen.findByRole("heading", { name: "Create your password" })).toBeVisible();
});

it("preserves the scrubbed fragment credential across React Strict Mode effect replay", async () => {
  const token = "invite_strict-mode-secret";
  window.history.replaceState(null, "", `/activate#token=${encodeURIComponent(token)}`);

  render(
    <StrictMode>
      <AccountActivation />
    </StrictMode>,
  );

  expect(await screen.findByRole("heading", { name: "Create your password" })).toBeVisible();
  expect(api.activationStatus).toHaveBeenCalledWith(token);
  expect(api.activationStatus).toHaveBeenCalledTimes(1);
  expect(window.location.hash).toBe("");
});

it("rejects activation pages without a fragment credential", async () => {
  render(<AccountActivation />);

  expect(await screen.findByRole("heading", { name: "Invitation unavailable" })).toBeVisible();
  expect(api.activationStatus).not.toHaveBeenCalled();
});
