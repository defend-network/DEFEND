import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MarketsShell } from "@/components/markets/MarketsShell";
import { PendingPanel } from "@/components/markets/PendingPanel";

vi.mock("next/navigation", () => ({ usePathname: () => "/markets" }));

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

  it("includes the shared product switcher with DEFEND AI and DEFENDcoder", () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    render(<MarketsShell>content</MarketsShell>);
    const switcher = screen.getByRole("navigation", { name: "DEFEND products" });
    expect(within(switcher).getByRole("link", { name: /DEFEND AI/ })).toBeDefined();
    expect(within(switcher).getByRole("link", { name: /DEFENDmarkets/ })).toBeDefined();
    expect(within(switcher).getByText(/DEFENDcoder/)).toBeDefined();
  });

  it("does not route into an offline product origin", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    render(<MarketsShell>content</MarketsShell>);
    const switcher = screen.getByRole("navigation", { name: "DEFEND products" });
    expect(await within(switcher).findByText("unavailable")).toBeDefined();
    expect(within(switcher).queryAllByRole("link", { name: /DEFENDcoder/ }).length).toBe(0);
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