import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { MfaSettings } from "@/components/auth/mfa-settings";
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
  const enabled = Boolean(
    (session.user as { twoFactorEnabled?: boolean }).twoFactorEnabled,
  );

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Account
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Security</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Manage multi-factor authentication for {session.user.email}.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Authenticator app</CardTitle>
        </CardHeader>
        <CardContent>
          <MfaSettings enabled={enabled} />
        </CardContent>
      </Card>
    </div>
  );
}
