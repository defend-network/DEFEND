import { MarketsShell } from "@/components/markets/MarketsShell";
import { OverviewPanel } from "@/components/markets/OverviewPanel";

export default function MarketsOverviewPage() {
  return (
    <MarketsShell>
      <OverviewPanel />
    </MarketsShell>
  );
}