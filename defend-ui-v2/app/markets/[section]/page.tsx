import { notFound } from "next/navigation";
import { MarketsShell } from "@/components/markets/MarketsShell";
import { MarketsSectionId } from "@/components/markets/marketsSections";
import { PendingPanel } from "@/components/markets/PendingPanel";
import { JournalPanel } from "@/components/markets/JournalPanel";

type PendingSectionId = Exclude<
  MarketsSectionId,
  "" | "sports" | "data-health" | "journal" | "arbitrage"
>;

const PENDING_SECTIONS: PendingSectionId[] = [
  "opportunities",
  "equities",
  "macro",
  "crypto",
  "events",
  "strategies",
  "backtests",
];

const PENDING_SET = new Set<PendingSectionId>(PENDING_SECTIONS);

export function generateStaticParams() {
  return PENDING_SECTIONS.map((section) => ({ section }));
}

// Next 15+/16 async route-parameter contract: params is a Promise and must be
// awaited. The prior sync `params: { section: string }` destructuring yielded
// `undefined` at runtime and triggered notFound() -> 404.
export default async function MarketsSectionPage({
  params,
}: {
  params: Promise<{ section: string }>;
}) {
  const { section } = await params;
  if (section === "journal") {
    return (
      <MarketsShell>
        <JournalPanel />
      </MarketsShell>
    );
  }
  if (!PENDING_SET.has(section as PendingSectionId)) {
    notFound();
  }
  return (
    <MarketsShell>
      <PendingPanel section={section as PendingSectionId} />
    </MarketsShell>
  );
}
