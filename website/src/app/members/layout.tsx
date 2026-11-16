import Link from "next/link";
import { redirect } from "next/navigation";

import { SignOutButton } from "@/components/auth/sign-out-button";
import { Logo } from "@/components/ui/logo";
import { getActor } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

const memberNav = [
  ["/members", "Dashboard"],
  ["/members/account", "Account"],
  ["/members/card", "Card"],
  ["/members/directory", "Directory"],
  ["/events", "Events"],
  ["/members/volunteers", "Volunteers"],
  ["/members/billing", "Billing"],
] as const;

export default async function MembersLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const actor = await getActor();
  if (!actor) {
    redirect("/login?next=/members");
  }

  return (
    <div className="min-h-screen bg-paper">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-20 w-full max-w-6xl items-center justify-between px-5 sm:px-8">
          <Logo />
          <div className="flex items-center gap-4">
            <span className="hidden text-sm text-slate-500 md:block">
              {actor.email}
            </span>
            <SignOutButton />
          </div>
        </div>
        <nav aria-label="Member navigation" className="border-t border-slate-100">
          <div className="mx-auto flex w-full max-w-6xl gap-1 overflow-x-auto px-5 py-2 sm:px-8">
            {memberNav.map(([href, label]) => (
              <Link
                key={href}
                href={href}
                className="whitespace-nowrap rounded-[var(--radius-control)] px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100 hover:text-navy-900"
              >
                {label}
              </Link>
            ))}
          </div>
        </nav>
      </header>
      <main className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8">
        {children}
      </main>
    </div>
  );
}
