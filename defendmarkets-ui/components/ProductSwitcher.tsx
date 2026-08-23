"use client";

export type MarketsProductId = "markets";

const PRODUCTS = [
  {
    id: "markets",
    label: "DEFENDmarkets",
    href: "/markets",
  },
] as const;

export function ProductSwitcher() {
  return (
    <nav className="dm-switcher" aria-label="DEFEND products">
      {PRODUCTS.map((product) => (
        <a
          key={product.id}
          className="dm-switcher-link"
          href={product.href}
          title={product.label}
        >
          <span className="dm-switcher-dot dm-switcher-dot-online" aria-hidden="true" />
          <span>{product.label}</span>
        </a>
      ))}
    </nav>
  );
}
