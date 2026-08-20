import { MarketsShell } from "@/components/markets/MarketsShell";
import { TableTennisBoard } from "@/components/markets/TableTennisBoard";
import { TTDataStatusPanel } from "@/components/markets/TTDataStatusPanel";
import { TTShadowPanel } from "@/components/markets/TTShadowPanel";

export default function MarketsSportsPage() {
  return (
    <MarketsShell>
      <TTDataStatusPanel />
      <TTShadowPanel />
      <TableTennisBoard />
    </MarketsShell>
  );
}