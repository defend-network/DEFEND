import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MarketsShell } from "@/components/markets/MarketsShell";
import { PendingPanel } from "@/components/markets/PendingPanel";

vi.mock("next/navigation", () => ({ usePathname: () => "/markets" }));

// M4.8.1 owner gate: MarketsShell is wrapped in MarketsOwnerGate. Mock a valid
// owner session so the gate renders the shell (not the login form).
vi.mock("@/lib/adminAuth", () => ({
  loadAdminSession: () => ({
    username: "owner",
    role: "owner",
    token: "test-token",
    loggedInAt: new Date().toISOString(),
    expiresAt: new Date(Date.now() + 3600000).toISOString(),
  }),
  isOwner: () => true,
  clearAdminSession: () => {},
  saveAdminSession: () => {},
}));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MarketsShell", () => {
  it("renders the full DEFENDmarkets navigation", () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    render(<MarketsShell>content</MarketsShell>);
    expect(screen.getAllByText("DEFENDmarkets").length).toBeGreaterThan(0);
    for (const label of [
      "Overview",
      "Opportunities",
      "Table Tennis",
      "Equities",
      "Macro",
      "Crypto",
      "Events",
      "Strategies",
      "Backtests",
      "Journal",
      "Data Health",
    ]) {
      expect(screen.getByRole("link", { name: label })).toBeDefined();
    }
  });

  it("includes the standalone DEFENDmarkets product switcher", () => {
    render(<MarketsShell>content</MarketsShell>);
    const switcher = screen.getByRole("navigation", { name: "DEFEND products" });
    expect(within(switcher).getByRole("link", { name: /DEFENDmarkets/ })).toBeDefined();
    // Standalone product: the switcher does not advertise sibling products
    // hosted by the DEFEND AI frontend.
    expect(within(switcher).queryByText(/DEFEND AI/)).toBeNull();
    expect(within(switcher).queryByText(/DEFENDcoder/)).toBeNull();
  });
});

describe("PendingPanel", () => {
  it("states honestly that a section is pending without fabricating metrics", () => {
    render(<PendingPanel section="equities" />);
    expect(screen.getByRole("heading", { name: "Equities" })).toBeDefined();
    expect(screen.getByText(/pending in DEFENDmarkets/i)).toBeDefined();
    expect(screen.getByText(/no data yet/i)).toBeDefined();
  });
});