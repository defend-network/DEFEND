import Link from "next/link";
import { redirect } from "next/navigation";

import { SignOutButton } from "@/components/auth/sign-out-button";
import { Logo } from "@/components/ui/logo";
import { getActor } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

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
            <Link
              href="/members"
              className="hidden text-sm font-semibold text-navy-800 hover:text-red-700 sm:block"
            >
              Member dashboard
            </Link>
            <span className="hidden text-sm text-slate-500 md:block">
              {actor.email}
            </span>
            <SignOutButton />
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl px-5 py-10 sm:px-8">
        {children}
      </main>
    </div>
  );
}
