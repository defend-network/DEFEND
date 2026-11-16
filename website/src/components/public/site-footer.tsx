import Link from "next/link";

import { Logo } from "@/components/ui/logo";
import { Container } from "@/components/ui/section";
import { footerNavigation, siteConfig } from "@/lib/config/site";

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-navy-800/10 bg-navy-900 text-slate-200">
      <Container className="py-14">
        <div className="grid gap-10 lg:grid-cols-[1.4fr_1fr_1fr]">
          <div className="space-y-5">
            <Logo href="/" size={52} tone="light" />
            <p className="max-w-md text-sm leading-6 text-slate-300">
              {siteConfig.expandedName}. A fraternal, cultural, and economic
              network being organized in Pasco County, Florida.
            </p>
            <p className="max-w-md text-xs leading-5 text-slate-400">
              {siteConfig.status.legal} {siteConfig.status.billing}
            </p>
          </div>

          {footerNavigation.map((group) => (
            <div key={group.heading}>
              <h2 className="text-[11px] font-bold uppercase tracking-[0.2em] text-slate-400">
                {group.heading}
              </h2>
              <ul className="mt-4 grid gap-2.5">
                {group.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="inline-flex min-h-6 items-center text-sm text-slate-200 underline-offset-4 hover:text-white hover:underline"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col gap-4 border-t border-white/10 pt-6 text-xs text-slate-400 sm:flex-row sm:items-center sm:justify-between">
          <p>
            Â© {new Date().getFullYear()} DEFEND. All rights reserved.
          </p>
          <p>
            Contact:{" "}
            <a
              href={`mailto:${siteConfig.contactEmail}`}
              className="underline underline-offset-4 hover:text-white"
            >
              {siteConfig.contactEmail}
            </a>
          </p>
        </div>
      </Container>
    </footer>
  );
}
