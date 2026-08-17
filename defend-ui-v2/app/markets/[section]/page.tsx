import { notFound } from "next/navigation";
import { MarketsShell } from "@/components/markets/MarketsShell";
import { MarketsSectionId } from "@/components/markets/marketsSections";
import { PendingPanel } from "@/components/markets/PendingPanel";

type PendingSectionId = Exclude<MarketsSectionId, "" | "sports" | "data-health">;

const PENDING_SECTIONS: PendingSectionId[] = [
  "opportunities",
  "equities",
  "macro",
  "crypto",
  "events",
  "strategies",
  "backtests",
  "journal",
];

const PENDING_SET = new Set<PendingSectionId>(PENDING_SECTIONS);

export function generateStaticParams() {
  return PENDING_SECTIONS.map((section) => ({ section }));
}

export default function MarketsSectionPage({
  params,
}: {
  params: { section: string };
}) {
  const { section } = params;
  if (!PENDING_SET.has(section as PendingSectionId)) {
    notFound();
  }
  return (
    <MarketsShell>
      <PendingPanel section={section as PendingSectionId} />
    </MarketsShell>
  );
}