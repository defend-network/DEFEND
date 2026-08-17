import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarketsShell } from "@/components/markets/MarketsShell";
import { PendingPanel } from "@/components/markets/PendingPanel";

vi.mock("next/navigation", () => ({ usePathname: () => "/markets" }));

describe("MarketsShell", () => {
  it("renders the full DEFENDmarkets navigation", () => {
    render(<MarketsShell>content</MarketsShell>);
    expect(screen.getByText("DEFENDmarkets")).toBeDefined();
    for (const label of [
      "Overview",
      "Opportunities",
      "Sports",
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
});

describe("PendingPanel", () => {
  it("states honestly that a section is pending without fabricating metrics", () => {
    render(<PendingPanel section="equities" />);
    expect(screen.getByRole("heading", { name: "Equities" })).toBeDefined();
    expect(screen.getByText(/pending in DEFENDmarkets/i)).toBeDefined();
    expect(screen.getByText(/no data yet/i)).toBeDefined();
  });
});