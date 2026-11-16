import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";
import { type ContentStatus, statusLabels } from "@/lib/config/site";

type BadgeVariant = "default" | "outline" | "red" | "green" | "amber";

const variants: Record<BadgeVariant, string> = {
  default: "bg-navy-800 text-white",
  outline: "border border-slate-300 bg-white text-slate-600",
  red: "bg-red-600/10 text-red-800",
  green: "bg-success-100 text-success-700",
  amber: "bg-warning-100 text-warning-700",
};

export function Badge({
  variant = "default",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { variant?: BadgeVariant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.12em]",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

const statusVariants: Record<ContentStatus, BadgeVariant> = {
  operating: "green",
  in_development: "amber",
  proposed: "outline",
  planned: "outline",
};

export function StatusBadge({ status }: { status: ContentStatus }) {
  return <Badge variant={statusVariants[status]}>{statusLabels[status]}</Badge>;
}
