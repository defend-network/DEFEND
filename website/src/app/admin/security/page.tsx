import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { MfaSettings } from "@/components/auth/mfa-settings";
import { SessionControls } from "@/components/auth/session-controls";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getActor, getSession } from "@/lib/auth/session";
import { listAdminMfaUsers } from "@/lib/auth/mfa-recovery";
import { can } from "@/lib/policy/permissions";
import { MfaRecoveryForm } from "./mfa-recovery-form";

export const metadata: Metadata = {
  title: "Admin Security",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function AdminSecurityPage() {
  const session = await getSession();
  if (!session?.user) redirect("/login?next=/admin/security");
  const actor = await getActor();
  const enabled = Boolean(
    (session.user as { twoFactorEnabled?: boolean }).twoFactorEnabled,
  );
  const emailVerified = Boolean(
    (session.user as { emailVerified?: boolean }).emailVerified,
  );
  const canRecover = actor ? can(actor, "system.users") : false;
  const adminUsers = canRecover ? await listAdminMfaUsers() : [];

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Administrative security
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Authentication and recovery</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
          Email is the default member method. Administrators should enable an
          authenticator app before performing sensitive actions. Email-only
          administrator sessions remain unverified for MFA-gated operations.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-2">
            <CardTitle className="text-lg">Email</CardTitle>
            <Badge variant={emailVerified ? "green" : "amber"}>
              {emailVerified ? "Verified" : "Not verified"}
            </Badge>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-2">
            <CardTitle className="text-lg">Phone / SMS</CardTitle>
            <Badge variant="outline">Not configured</Badge>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-2">
            <CardTitle className="text-lg">Authenticator</CardTitle>
            <Badge variant={enabled ? "green" : "amber"}>
              {enabled ? "Enabled" : "Not configured"}
            </Badge>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-2">
            <CardTitle className="text-lg">Passkey</CardTitle>
            <Badge variant="outline">Not available</Badge>
          </CardHeader>
        </Card>
      </div>

      {!enabled ? (
        <Alert tone="warning">
          Enable an authenticator app before performing sensitive administrative
          actions. Email-only sessions can sign in, but MFA-gated operations fail
          closed until a strong factor is verified.
        </Alert>
      ) : null}

      <Alert tone="warning">
        Store recovery codes securely. Owner-assisted reset is available only to
        an authorized owner and is recorded in the audit log. Reset revokes the
        target user&apos;s sessions.
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>Authenticator app and recovery codes</CardTitle>
        </CardHeader>
        <CardContent>
          <MfaSettings enabled={enabled} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Active sessions</CardTitle>
        </CardHeader>
        <CardContent>
          <SessionControls />
        </CardContent>
      </Card>

      {canRecover ? (
        <Card>
          <CardHeader>
            <CardTitle>Administrative MFA recovery</CardTitle>
            <p className="text-sm leading-6 text-slate-600">
              Reset MFA only after verifying the administrator&apos;s identity
              through an approved recovery process. The action is audited.
            </p>
          </CardHeader>
          <CardContent>
            {adminUsers.length === 0 ? (
              <p className="text-sm text-slate-500">No administrative accounts found.</p>
            ) : (
              <ul className="grid gap-3">
                {adminUsers.map((admin) => (
                  <li key={admin.userId} className="grid gap-3 rounded-[var(--radius-control)] border border-slate-200 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-semibold text-navy-900">{admin.name}</p>
                        <p className="text-xs text-slate-500">{admin.email}</p>
                      </div>
                      <Badge variant={admin.twoFactorEnabled ? "green" : "amber"}>
                        {admin.twoFactorEnabled ? "MFA enabled" : "MFA not enabled"}
                      </Badge>
                    </div>
                    {admin.twoFactorEnabled ? (
                      <MfaRecoveryForm targetUserId={admin.userId} />
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
