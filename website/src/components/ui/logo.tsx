import Image from "next/image";
import Link from "next/link";

import { cn } from "@/lib/utils";

export function Logo({
  href = "/",
  className,
  showWordmark = true,
  size = 48,
  tone = "dark",
}: {
  href?: string | null;
  className?: string;
  showWordmark?: boolean;
  size?: number;
  tone?: "dark" | "light";
}) {
  const content = (
    <span className={cn("inline-flex items-center gap-3", className)}>
      <span
        className="relative block shrink-0 overflow-hidden rounded-[6px] border border-slate-300/40 bg-navy-950 shadow-sm"
        style={{ width: size, height: size }}
      >
        <Image
          src="/defend-logo.png"
          alt="DEFEND"
          fill
          priority
          sizes={`${size}px`}
          className="object-cover"
        />
      </span>
      {showWordmark ? (
        <span className="grid gap-0.5">
          <span
            className={cn(
              "font-serif text-xl font-semibold tracking-[0.16em]",
              tone === "light" ? "text-white" : "text-navy-900",
            )}
          >
            DEFEND
          </span>
          <span
            className={cn(
              "hidden text-[10px] font-semibold uppercase tracking-[0.16em] sm:block",
              tone === "light" ? "text-slate-400" : "text-slate-500",
            )}
          >
            Fraternal Economic Network
          </span>
        </span>
      ) : null}
    </span>
  );

  if (!href) return content;
  return (
    <Link href={href} title="Home" className="inline-flex">
      {content}
    </Link>
  );
}
