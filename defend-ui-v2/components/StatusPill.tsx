import type { ResearchStatus } from "@/lib/api";

export function StatusPill({ status }: { status?: ResearchStatus }) {
  if (!status) return null;
  const label =
    status === "insufficient_evidence"
      ? "Insufficient evidence"
      : status === "direct"
        ? "Direct"
        : status[0].toUpperCase() + status.slice(1);
  return <span className={`pill pill-${status}`}>{label}</span>;
}
