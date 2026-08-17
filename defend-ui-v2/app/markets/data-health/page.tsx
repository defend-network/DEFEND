import { MarketsShell } from "@/components/markets/MarketsShell";
import { DataHealthPanel } from "@/components/markets/DataHealthPanel";

export default function MarketsDataHealthPage() {
  return (
    <MarketsShell>
      <DataHealthPanel />
    </MarketsShell>
  );
}