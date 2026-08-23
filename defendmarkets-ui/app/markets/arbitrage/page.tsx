import { MarketsShell } from "@/components/markets/MarketsShell";
import { OwnerArbitrage } from "@/components/markets/OwnerArbitrage";

export default function MarketsArbitragePage() {
  return (
    <MarketsShell>
      <OwnerArbitrage />
    </MarketsShell>
  );
}
