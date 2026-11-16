import type { InputHTMLAttributes, TextareaHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Input({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-11 w-full rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-[15px] text-navy-900 shadow-sm outline-none transition-colors placeholder:text-slate-400 focus:border-navy-700 focus:ring-2 focus:ring-navy-800/15 disabled:cursor-not-allowed disabled:bg-slate-100",
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "flex min-h-28 w-full rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 py-2.5 text-[15px] text-navy-900 shadow-sm outline-none transition-colors placeholder:text-slate-400 focus:border-navy-700 focus:ring-2 focus:ring-navy-800/15 disabled:cursor-not-allowed disabled:bg-slate-100",
        className,
      )}
      {...props}
    />
  );
}
