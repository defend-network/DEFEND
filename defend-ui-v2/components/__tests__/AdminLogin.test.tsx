import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import AdminLogin from "../AdminLogin";
import * as api from "@/lib/api";

vi.mock("@/lib/api", () => ({
  adminLogin: vi.fn(),
}));

const session = {
  username: "owner@defend-network.org",
  role: "owner" as const,
  token: "token-1",
  loggedInAt: "2026-08-17T00:00:00.000Z",
  expiresAt: "2026-08-17T01:00:00.000Z",
};

describe("AdminLogin branding", () => {
  it("keeps DEFEND AI branding by default", () => {
    render(<AdminLogin onSuccess={() => {}} />);

    expect(
      screen.getByRole("heading", { name: "Admin access" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "DEFEND AI home" })).toBeVisible();
    expect(
      screen.getByRole("link", { name: "← Back to DEFEND AI" }),
    ).toBeVisible();
  });

  it("renders platform branding for the shared control plane", () => {
    render(
      <AdminLogin
        onSuccess={() => {}}
        eyebrow="Platform administration"
        title="ADMIN SETUP"
        description="Platform administration & integrations"
        headerLabel="DEFEND PLATFORM"
        headerHref={null}
        backHref={null}
        backLabel={null}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "ADMIN SETUP" }),
    ).toBeVisible();
    expect(
      screen.getByText("Platform administration & integrations"),
    ).toBeVisible();
    expect(screen.getByText("DEFEND PLATFORM")).toBeVisible();
    expect(
      screen.queryByRole("link", { name: "DEFEND AI home" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Back to DEFEND AI/)).not.toBeInTheDocument();
    expect(screen.queryByText(/DEFEND AI/)).not.toBeInTheDocument();
  });

  it("logs in and forwards the admin session unchanged", async () => {
    vi.mocked(api.adminLogin).mockResolvedValue({
      username: session.username,
      role: session.role,
      token: session.token,
      expires_in: 3600,
    });
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    render(<AdminLogin onSuccess={onSuccess} />);

    await user.type(
      screen.getByPlaceholderText("Username"),
      session.username,
    );
    await user.type(screen.getByPlaceholderText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: "Unlock" }));

    await waitFor(() =>
      expect(onSuccess).toHaveBeenCalledWith(
        expect.objectContaining({
          username: session.username,
          role: "owner",
          token: session.token,
        }),
      ),
    );
    expect(api.adminLogin).toHaveBeenCalledWith(session.username, "secret");
  });
});