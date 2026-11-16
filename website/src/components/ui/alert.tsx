import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type AlertTone = "info" | "success" | "warning" | "error";

const tones: Record<AlertTone, string> = {
  info: "border-navy-700/20 bg-navy-800/[0.04] text-navy-800",
  success: "border-success-700/20 bg-success-100 text-success-700",
  warning: "border-warning-700/20 bg-warning-100 text-warning-700",
  error: "border-error-700/20 bg-error-100 text-error-700",
};

export function Alert({
  tone = "info",
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & { tone?: AlertTone }) {
  return (
    <div
      className={cn(
        "rounded-[var(--radius-control)] border px-4 py-3 text-sm leading-6",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-[var(--radius-card)] border border-dashed border-slate-300 bg-paper px-6 py-12 text-center">
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
        {description}
      </p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
