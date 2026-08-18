import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SetupPage from "../page";
import * as adminAuth from "@/lib/adminAuth";
import * as api from "@/lib/api";
import * as setupApi from "@/lib/setupApi";

vi.mock("@/lib/adminAuth", () => ({
  loadAdminSession: vi.fn(),
  saveAdminSession: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  adminLogin: vi.fn(),
}));

vi.mock("@/lib/setupApi", () => ({
  getSetupSummary: vi.fn(),
  getSetupDiagnostics: vi.fn(),
  testAllSetupProviders: vi.fn(),
}));

const summary = {
  categories: [
    { category_id: "core", display_name: "Core", providers: [] },
  ],
  products: [{ product_id: "defend", display_name: "DEFEND AI" }],
  product_providers: {},
  legacy_secret_names: [],
  registry_secret_names: [],
};

beforeEach(() => {
  vi.mocked(adminAuth.loadAdminSession).mockReset();
  vi.mocked(api.adminLogin).mockReset();
  vi.mocked(setupApi.getSetupSummary)
    .mockReset()
    .mockResolvedValue(summary);
  vi.mocked(setupApi.getSetupDiagnostics)
    .mockReset()
    .mockResolvedValue({ rows: [] });
});

describe("Setup page authentication", () => {
  it("shows the platform-branded login when no session exists", async () => {
    vi.mocked(adminAuth.loadAdminSession).mockReturnValue(null);
    const { container } = render(<SetupPage />);

    expect(
      await screen.findByRole("heading", { name: "ADMIN SETUP" }),
    ).toBeVisible();
    expect(screen.getByText("DEFEND PLATFORM")).toBeVisible();
    expect(screen.getByText("Platform administration & integrations")).toBeVisible();
    expect(screen.queryByText(/Back to DEFEND AI/)).not.toBeInTheDocument();
    expect(container.querySelector("[data-setup-shell]")).toBeNull();
  });

  it("loads Setup on the same route after successful authentication", async () => {
    vi.mocked(adminAuth.loadAdminSession).mockReturnValue(null);
    vi.mocked(api.adminLogin).mockResolvedValue({
      username: "owner@defend-network.org",
      role: "owner",
      token: "token-1",
      expires_in: 3600,
    });
    const user = userEvent.setup();
    const { container } = render(<SetupPage />);

    await user.type(
      await screen.findByPlaceholderText("Username"),
      "owner@defend-network.org",
    );
    await user.type(screen.getByPlaceholderText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: "Unlock" }));

    expect(
      await screen.findByRole("heading", { name: "Setup & Integrations" }),
    ).toBeVisible();
    expect(container.querySelector("[data-setup-shell]")).not.toBeNull();
    expect(
      await screen.findByRole("tablist", { name: "Provider categories" }),
    ).toBeVisible();
    expect(screen.getByRole("tab", { name: "Core" })).toBeVisible();
    expect(setupApi.getSetupSummary).toHaveBeenCalledWith("token-1");
    expect(screen.queryByRole("heading", { name: "ADMIN SETUP" })).not.toBeInTheDocument();
  });

  it("stays on the setup route instead of redirecting to DEFEND AI admin", async () => {
    vi.mocked(adminAuth.loadAdminSession).mockReturnValue(null);
    render(<SetupPage />);

    expect(
      await screen.findByRole("heading", { name: "ADMIN SETUP" }),
    ).toBeVisible();
    expect(screen.queryByRole("link", { name: "DEFEND AI home" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Back to DEFEND AI/)).not.toBeInTheDocument();
    expect(screen.queryByText(/admin workspace/i)).not.toBeInTheDocument();
  });
});