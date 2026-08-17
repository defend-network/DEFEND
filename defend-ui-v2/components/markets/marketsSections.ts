export const MARKETS_SECTIONS = [
  { id: "", label: "Overview" },
  { id: "opportunities", label: "Opportunities" },
  { id: "sports", label: "Sports" },
  { id: "equities", label: "Equities" },
  { id: "macro", label: "Macro" },
  { id: "crypto", label: "Crypto" },
  { id: "events", label: "Events" },
  { id: "strategies", label: "Strategies" },
  { id: "backtests", label: "Backtests" },
  { id: "journal", label: "Journal" },
  { id: "data-health", label: "Data Health" },
] as const;

export type MarketsSectionId = (typeof MARKETS_SECTIONS)[number]["id"];