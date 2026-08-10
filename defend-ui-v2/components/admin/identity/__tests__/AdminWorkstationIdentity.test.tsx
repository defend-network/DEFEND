import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { AdminWorkstation } from "../../../AdminWorkstation";
import * as identityApi from "@/lib/identityApi";

vi.mock("@/lib/adminAuth", async () => {
  const actual = await vi.importActual<typeof import("@/lib/adminAuth")>(
    "@/lib/adminAuth",
  );
  return {
    ...actual,
    loadAdminSession: () => ({
      username: "chairman@defend-network.org",
      role: "owner" as const,
      token: "owner-token",
      loggedInAt: "2026-08-10T12:00:00.000Z",
      expiresAt: "2026-08-10T13:00:00.000Z",
    }),
  };
});

vi.mock("@/lib/api", () => ({
  adminDocuments: vi.fn().mockResolvedValue({ documents: [] }),
  adminHealth: vi.fn().mockResolvedValue({ ok: true, tools: [] }),
  adminLogout: vi.fn().mockResolvedValue(undefined),
  adminResearch: vi.fn(),
}));

vi.mock("@/lib/identityApi", async () => {
  const actual = await vi.importActual<typeof import("@/lib/identityApi")>(
    "@/lib/identityApi",
  );
  return {
    ...actual,
    listAccounts: vi.fn(),
    listVisitors: vi.fn(),
    listInvitations: vi.fn(),
  };
});

const emptyPage = { items: [], total: 0, limit: 50, offset: 0 };

beforeEach(() => {
  vi.mocked(identityApi.listAccounts).mockReset().mockResolvedValue(emptyPage);
  vi.mocked(identityApi.listVisitors).mockReset().mockResolvedValue(emptyPage);
  vi.mocked(identityApi.listInvitations).mockReset().mockResolvedValue(emptyPage);
});

it("opens the real identity workspace in its responsive main region", async () => {
  const user = userEvent.setup();
  render(<AdminWorkstation />);

  await user.click(await screen.findByRole("button", { name: "Users & Roles" }));

  expect(await screen.findByRole("tab", { name: "Accounts" })).toBeVisible();
  expect(screen.getByRole("main")).toHaveClass("admin-main--identity");
  expect(screen.queryByText(/Single-operator mode/i)).not.toBeInTheDocument();
});
