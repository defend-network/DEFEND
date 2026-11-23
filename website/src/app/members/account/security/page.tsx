import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { MfaSettings } from "@/components/auth/mfa-settings";
import { SessionControls } from "@/components/auth/session-controls";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getSession } from "@/lib/auth/session";

export const metadata: Metadata = {
  title: "Account Security",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function MemberSecurityPage() {
  const session = await getSession();
  if (!session?.user) redirect("/login?next=/members/account/security");
  const emailVerified = Boolean(
    (session.user as { emailVerified?: boolean }).emailVerified,
  );
  const twoFactorEnabled = Boolean(
    (session.user as { twoFactorEnabled?: boolean }).twoFactorEnabled,
  );

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Account
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Security</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
          Email is the default sign-in and verification method. You can add an
          authenticator app as an optional stronger factor for sensitive
          actions.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3">
            <div>
              <CardTitle>Email</CardTitle>
              <p className="mt-1 text-xs text-slate-500">{session.user.email}</p>
            </div>
            <Badge variant={emailVerified ? "green" : "amber"}>
              {emailVerified ? "Verified" : "Not verified"}
            </Badge>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-slate-600">
              Default method for sign-in codes and account notifications.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3">
            <CardTitle>Phone / SMS</CardTitle>
            <Badge variant="outline">Not configured</Badge>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-slate-600">
              SMS verification requires an approved DEFEND messaging provider.
              No SMS is sent until that provider is configured.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3">
            <CardTitle>Authenticator app</CardTitle>
            <Badge variant={twoFactorEnabled ? "green" : "outline"}>
              {twoFactorEnabled ? "Enabled" : "Not configured"}
            </Badge>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-slate-600">
              Optional TOTP authenticator. Recommended for administrators and
              for sensitive actions.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-start justify-between gap-3">
            <CardTitle>Passkey</CardTitle>
            <Badge variant="outline">Not available</Badge>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-slate-600">
              Passkeys are not available in this build. No passkey credential is
              currently stored or accepted.
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Authenticator app and recovery codes</CardTitle>
        </CardHeader>
        <CardContent>
          <MfaSettings enabled={twoFactorEnabled} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Active sessions</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="mb-4 text-sm leading-6 text-slate-600">
            Signing out other sessions does not affect this session. Use it after
            changing your password or if you suspect unauthorized access.
          </p>
          <SessionControls />
        </CardContent>
      </Card>

      <Alert tone="info">
        Email verification codes expire quickly and can be used once. Recovery
        codes are single-use and should be stored offline, not shared.
      </Alert>
    </div>
  );
}
