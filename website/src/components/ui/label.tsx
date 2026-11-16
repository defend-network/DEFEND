import type { LabelHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Label({
  className,
  ...props
}: LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn(
        "text-sm font-semibold text-navy-800",
        className,
      )}
      {...props}
    />
  );
}

export function FieldError({ children }: { children?: string }) {
  if (!children) return null;
  return (
    <p className="text-sm font-medium text-error-700" role="alert">
      {children}
    </p>
  );
}
