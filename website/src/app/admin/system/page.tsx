import type { Metadata } from "next";
import { desc } from "drizzle-orm";
import { format } from "date-fns";

import { AdminAccessDenied } from "@/components/admin/access-denied";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminPageActor } from "@/lib/auth/admin";
import { getDb } from "@/lib/db/client";
import { listRecentAuditEvents } from "@/lib/audit/audit";
import { listUsersAndRoles } from "@/lib/auth/roles";
import { listFeatureReleases } from "@/lib/platform/releases";
import { stripeConfigured } from "@/lib/payments/stripe";
import { can } from "@/lib/policy/permissions";
import { chapters } from "@/db/schema";
import { RoleAssignmentForm, RevokeRoleForm } from "./system-forms";

export const metadata: Metadata = {
  title: "System",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function SystemPage() {
  const { actor, allowed } = await adminPageActor("system.audit");
  if (!allowed) return <AdminAccessDenied module="system" />;
  const canManageUsers = can(actor, "system.users");
  const db = await getDb();
  const [roleData, auditEvents, chapterRows, releases] = await Promise.all([
    canManageUsers
      ? listUsersAndRoles()
      : Promise.resolve({ users: [], assignments: [] }),
    listRecentAuditEvents(25),
    db.select({ id: chapters.id, name: chapters.name }).from(chapters).orderBy(desc(chapters.createdAt)).limit(50),
    listFeatureReleases(),
  ]);

  const integrations = [
    {
      name: "Database",
      status: "connected",
      detail: "D1 binding responds.",
    },
    {
      name: "Email transport",
      status: process.env.EMAIL_TRANSPORT || (process.env.APP_ENV === "production" ? "not_configured" : "outbox"),
      detail: process.env.EMAIL_TRANSPORT === "resend" ? "Resend selected." : "Development outbox selected.",
    },
    {
      name: "Turnstile",
      status: process.env.TURNSTILE_SECRET_KEY ? "configured" : "not_configured",
      detail: process.env.TURNSTILE_SECRET_KEY ? "Server verification key present." : "Public forms fail closed in production.",
    },
    {
      name: "Stripe",
      status: stripeConfigured() ? "configured" : "not_configured",
      detail: stripeConfigured() ? "Test/live keys present; live approval flag controls charging." : "No Stripe credentials.",
    },
    {
      name: "Backups",
      status: "not_configured",
      detail: "Scheduled D1 export to R2 is not enabled.",
    },
  ];

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Administration
        </p>
        <h1 className="mt-3 text-3xl font-semibold">System</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Roles, integration status, audit history, and operational health.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {integrations.map((integration) => (
          <Card key={integration.name}>
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="text-lg">{integration.name}</CardTitle>
                <Badge variant={integration.status === "connected" || integration.status === "configured" ? "green" : integration.status === "not_configured" ? "amber" : "outline"}>
                  {integration.status.replaceAll("_", " ")}
                </Badge>
              </div>
              <p className="text-xs leading-5 text-slate-500">{integration.detail}</p>
            </CardHeader>
          </Card>
        ))}
      </div>

      {canManageUsers ? (
        <>
          <div className="grid gap-5 xl:grid-cols-2">
            <RoleAssignmentForm users={roleData.users} chapters={chapterRows} />
            <Card>
              <CardHeader><CardTitle>Active role assignments</CardTitle></CardHeader>
              <CardContent>
                {roleData.assignments.length === 0 ? <p className="text-sm text-slate-500">No role assignments.</p> : (
                  <ul className="grid gap-2 text-sm">
                    {roleData.assignments.map((assignment) => {
                      const account = roleData.users.find((candidate) => candidate.id === assignment.userId);
                      return (
                        <li key={assignment.id} className="grid gap-2 rounded-[var(--radius-control)] border border-slate-200 p-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <p className="font-semibold text-navy-900">{account?.name ?? assignment.userId}</p>
                              <p className="text-xs text-slate-500">{account?.email ?? ""} Â· {assignment.roleKey} Â· {assignment.scopeType}{assignment.scopeId ? ` (${assignment.scopeId})` : ""}</p>
                            </div>
                            {assignment.roleKey !== "owner" ? <RevokeRoleForm assignmentId={assignment.id} /> : <Badge variant="green">owner</Badge>}
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader><CardTitle>Users</CardTitle></CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[700px] text-left text-sm">
                  <thead className="border-b border-slate-200 text-xs uppercase tracking-[0.12em] text-slate-500"><tr><th className="px-3 py-3">User</th><th className="px-3 py-3">MFA</th><th className="px-3 py-3">Email</th></tr></thead>
                  <tbody>{roleData.users.map((account) => <tr key={account.id} className="border-b border-slate-100 last:border-0"><td className="px-3 py-3"><p className="font-semibold text-navy-900">{account.name}</p><p className="text-xs text-slate-500">{account.id}</p></td><td className="px-3 py-3"><Badge variant={account.twoFactorEnabled ? "green" : "amber"}>{account.twoFactorEnabled ? "enabled" : "not enabled"}</Badge></td><td className="px-3 py-3 text-slate-600">{account.email}</td></tr>)}</tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      ) : (
        <Alert tone="info">
          User and role administration requires the owner-only system.users permission.
        </Alert>
      )}

      <Card>
        <CardHeader><CardTitle>Feature release status</CardTitle></CardHeader>
        <CardContent>
          {releases.length === 0 ? (
            <p className="text-sm text-slate-500">No release records.</p>
          ) : (
            <ul className="grid gap-2 text-sm">
              {releases.map((release) => (
                <li
                  key={release.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-control)] border border-slate-200 p-3"
                >
                  <span>
                    <strong className="text-navy-900">{release.name}</strong>
                    <span className="ml-2 text-xs text-slate-500">
                      {release.moduleKey}
                    </span>
                  </span>
                  <Badge
                    variant={
                      release.state === "publicly_activated"
                        ? "green"
                        : release.state === "implemented"
                          ? "outline"
                          : "amber"
                    }
                  >
                    {release.state.replaceAll("_", " ")}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Alert tone="info">
        Backup status is not configured. Do not treat this environment as production-ready until D1 export/restore and R2 backup drills are completed.
      </Alert>

      <Card>
        <CardHeader><CardTitle>Recent audit events</CardTitle></CardHeader>
        <CardContent>
          {auditEvents.length === 0 ? <p className="text-sm text-slate-500">No audit events.</p> : (
            <ul className="grid gap-2 text-sm">
              {auditEvents.map((event) => (
                <li key={event.id} className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-control)] border border-slate-200 p-3">
                  <span><strong className="text-navy-900">{event.action}</strong><span className="ml-2 text-xs text-slate-500">{event.targetType} Â· {event.targetId ?? "â€”"}</span></span>
                  <span className="text-xs text-slate-500">{event.outcome} Â· {format(event.createdAt, "MMM d, yyyy h:mm a")}</span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
