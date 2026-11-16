import Link from "next/link";
import { redirect } from "next/navigation";

import { SignOutButton } from "@/components/auth/sign-out-button";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Logo } from "@/components/ui/logo";
import { getActor } from "@/lib/auth/session";
import { can } from "@/lib/policy/permissions";

export const dynamic = "force-dynamic";

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const actor = await getActor();
  if (!actor) {
    redirect("/login?next=/admin");
  }

  const allowed = can(actor, "applications.view");

  return (
    <div className="min-h-screen bg-paper">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-20 w-full max-w-7xl items-center justify-between gap-4 px-5 sm:px-8">
          <div className="flex items-center gap-5">
            <Logo />
            <div className="hidden border-l border-slate-200 pl-5 md:block">
              <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-red-700">
                Administrative workstation
              </p>
              <p className="text-xs text-slate-500">{actor.email}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Button asChild variant="ghost" size="sm">
              <Link href="/members">Member view</Link>
            </Button>
            <SignOutButton />
          </div>
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-7xl gap-8 px-5 py-8 sm:px-8 lg:grid-cols-[220px_1fr]">
        <aside className="h-fit rounded-[var(--radius-card)] border border-slate-200 bg-white p-3">
          <p className="px-3 pb-2 pt-1 text-[10px] font-bold uppercase tracking-[0.2em] text-slate-600">
            Workstation
          </p>
          <nav aria-label="Admin navigation" className="grid gap-1">
            <Link
              href="/admin"
              className="rounded-[var(--radius-control)] bg-navy-800 px-3 py-2.5 text-sm font-semibold text-white"
            >
              Overview
            </Link>
            <Link
              href="/admin/applications"
              className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900"
            >
              Applications
            </Link>
            <Link
              href="/admin/members"
              className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900"
            >
              Members
            </Link>
            <Link href="/admin/chapters" className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900">Chapters</Link>
            <Link href="/admin/crm" className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900">CRM</Link>
            <Link href="/admin/facilities" className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900">Facilities</Link>
            <Link
              href="/admin/events"
              className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900"
            >
              Events
            </Link>
            <Link href="/admin/programs" className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900">Programs</Link>
            <Link
              href="/admin/check-in"
              className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900"
            >
              Check-in
            </Link>
            <Link href="/admin/documents" className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900">Documents</Link>
            <Link href="/admin/website" className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900">Website</Link>
            <Link href="/admin/communications" className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900">Communications</Link>
            <Link href="/admin/finance" className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900">Finance</Link>
            <Link href="/admin/system" className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900">System</Link>
            <Link
              href="/admin/security"
              className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900"
            >
              Security / MFA
            </Link>
            {process.env.APP_ENV !== "production" ? (
              <Link
                href="/dev/outbox"
                className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-500 hover:bg-slate-100 hover:text-navy-900"
              >
                Dev outbox
              </Link>
            ) : null}
          </nav>
          <p className="mt-4 border-t border-slate-100 px-3 pt-4 text-xs leading-5 text-slate-500">
            Additional modules are being implemented in the next milestone.
          </p>
        </aside>

        <main>
          {!allowed ? (
            <Card>
              <CardHeader>
                <CardTitle>Access denied</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-slate-600">
                  Your account does not have administrative access. Contact the
                  DEFEND owner if you believe this is an error.
                </p>
              </CardContent>
            </Card>
          ) : (
            children
          )}
        </main>
      </div>
    </div>
  );
}
