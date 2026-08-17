"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MARKETS_SECTIONS } from "@/components/markets/marketsSections";
import { ProductSwitcher } from "@/components/ProductSwitcher";

export type { MarketsSectionId } from "@/components/markets/marketsSections";

export function MarketsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const active = pathname.replace(/^\/markets\/?/, "");

  return (
    <div className="markets-shell">
      <header className="markets-header">
        <div className="markets-header-top">
          <Link href="/markets" className="markets-brand">
            DEFENDmarkets
          </Link>
          <ProductSwitcher />
        </div>
        <nav className="markets-nav" aria-label="Markets sections">
          {MARKETS_SECTIONS.map((section) => (
            <Link
              key={section.id}
              href={`/markets${section.id ? `/${section.id}` : ""}`}
              className={`markets-nav-link${active === section.id ? " active" : ""}`}
            >
              {section.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="markets-main">{children}</main>
    </div>
  );
}

export function MarketsStatus({ state }: { state: string }) {
  return (
    <span className={`markets-status markets-status-${state.toLowerCase()}`}>
      {state}
    </span>
  );
}