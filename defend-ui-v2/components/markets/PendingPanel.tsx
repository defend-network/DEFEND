"use client";

import { MarketsSectionId } from "@/components/markets/MarketsShell";

export function PendingPanel({ section }: { section: MarketsSectionId }) {
  return (
    <section className="markets-panel">
      <h2>{section.charAt(0).toUpperCase() + section.slice(1)}</h2>
      <p className="markets-note">
        This section is pending in DEFENDmarkets and shows no data yet. It will be
        populated when the underlying desk is implemented.
      </p>
    </section>
  );
}