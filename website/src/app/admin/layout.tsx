import Link from "next/link";
import { redirect } from "next/navigation";

import { SignOutButton } from "@/components/auth/sign-out-button";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Logo } from "@/components/ui/logo";
import { getActor } from "@/lib/auth/session";
import {
  can,
  canAccessModule,
  hasAnyAdminPermission,
  type Permission,
} from "@/lib/policy/permissions";

export const dynamic = "force-dynamic";

type NavItem = {
  href: string;
  label: string;
  permission?: Permission;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/applications", label: "Applications", permission: "applications.view" },
  { href: "/admin/members", label: "Members", permission: "members.view" },
  { href: "/admin/chapters", label: "Chapters", permission: "chapters.view" },
  { href: "/admin/crm", label: "CRM", permission: "crm.view" },
  { href: "/admin/facilities", label: "Facilities", permission: "facilities.view" },
  { href: "/admin/events", label: "Events", permission: "events.view" },
  { href: "/admin/programs", label: "Programs", permission: "programs.view" },
  { href: "/admin/check-in", label: "Check-in", permission: "events.checkin" },
  { href: "/admin/documents", label: "Documents", permission: "documents.view" },
  { href: "/admin/website", label: "Website", permission: "cms.edit" },
  { href: "/admin/communications", label: "Communications", permission: "communications.view" },
  { href: "/admin/finance", label: "Finance", permission: "finance.view" },
  { href: "/admin/system", label: "System", permission: "system.audit" },
  { href: "/admin/security", label: "Security / MFA", permission: "system.users" },
];

export default async function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const actor = await getActor();
  if (!actor) {
    redirect("/login?next=/admin");
  }

  const allowed = hasAnyAdminPermission(actor);

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
            {NAV_ITEMS.filter(
              (item) => !item.permission || canAccessModule(actor, item.permission),
            ).map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-600 hover:bg-slate-100 hover:text-navy-900"
              >
                {item.label}
              </Link>
            ))}
            {process.env.APP_ENV !== "production" && can(actor, "system.users") ? (
              <Link
                href="/dev/outbox"
                className="rounded-[var(--radius-control)] px-3 py-2.5 text-sm text-slate-500 hover:bg-slate-100 hover:text-navy-900"
              >
                Dev outbox
              </Link>
            ) : null}
          </nav>
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
