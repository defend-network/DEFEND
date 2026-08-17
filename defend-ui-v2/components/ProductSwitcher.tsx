"use client";

import { useEffect, useState } from "react";

export type ProductId = "defend-ai" | "markets" | "coder";

type ProductStatus = "online" | "offline" | "checking";

type ProductEntry = {
  id: ProductId;
  label: string;
  href: string;
  probeUrl: string | null;
};

const PRODUCTS: ProductEntry[] = [
  {
    id: "defend-ai",
    label: "DEFEND AI",
    href: "/",
    probeUrl: null,
  },
  {
    id: "markets",
    label: "DEFENDmarkets",
    href: "/markets",
    probeUrl: null,
  },
  {
    id: "coder",
    label: "DEFENDcoder",
    href: "https://defendcoder.defend-network.org",
    probeUrl: "https://defendcoder.defend-network.org",
  },
];

const PROBE_TIMEOUT_MS = 2500;

function probeOrigin(url: string): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    return fetch(url, { method: "HEAD", mode: "no-cors", signal: controller.signal })
      .then(() => true)
      .catch(() => false)
      .finally(() => clearTimeout(timer));
  } catch {
    clearTimeout(timer);
    return Promise.resolve(false);
  }
}

export function ProductSwitcher() {
  const [statuses, setStatuses] = useState<Record<ProductId, ProductStatus>>({
    "defend-ai": "online",
    markets: "online",
    coder: "checking",
  });

  useEffect(() => {
    let cancelled = false;
    for (const product of PRODUCTS) {
      if (!product.probeUrl) continue;
      probeOrigin(product.probeUrl).then((reachable) => {
        if (!cancelled) {
          setStatuses((prev) => ({
            ...prev,
            [product.id]: reachable ? "online" : "offline",
          }));
        }
      });
    }
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <nav className="dm-switcher" aria-label="DEFEND products">
      {PRODUCTS.map((product) => {
        const status = statuses[product.id];
        const offline = status === "offline";
        const inner = (
          <>
            <span
              className={`dm-switcher-dot dm-switcher-dot-${status}`}
              aria-hidden="true"
            />
            <span>{product.label}</span>
            {offline && <span className="dm-switcher-offline">unavailable</span>}
          </>
        );
        return offline ? (
          <span
            key={product.id}
            className="dm-switcher-link dm-switcher-link-offline"
            title="Product is offline — not routed"
            aria-disabled="true"
          >
            {inner}
          </span>
        ) : (
          <a
            key={product.id}
            className="dm-switcher-link"
            href={product.href}
            title={`${product.label}${status === "checking" ? " (checking availability)" : ""}`}
          >
            {inner}
          </a>
        );
      })}
    </nav>
  );
}