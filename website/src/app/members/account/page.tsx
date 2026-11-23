import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { VerificationNotice } from "@/components/auth/verification-notice";
import { getActor, getSession } from "@/lib/auth/session";
import { getMemberAccount } from "@/lib/membership/profile";
import { AccountForm } from "./account-form";

export const metadata: Metadata = {
  title: "Account Settings",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function AccountPage() {
  const actor = await getActor();
  if (!actor) redirect("/login?next=/members/account");
  const session = await getSession();
  const account = await getMemberAccount(actor.userId);
  const emailVerified = Boolean(session?.user.emailVerified);

  if (!account.profile) {
    return (
      <Alert tone="warning">
        Your member profile is not available yet. Contact DEFEND if this
        persists.
      </Alert>
    );
  }

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Member account
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Profile and settings</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            Contact information, directory visibility, and notification preferences.
          </p>
        </div>
        <div className="flex gap-2">
          <Button asChild variant="secondary" size="sm">
            <Link href="/members/account/security">Security / MFA</Link>
          </Button>
          <Button asChild variant="secondary" size="sm">
            <Link href="/members">Dashboard</Link>
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{account.profile.legalFirstName} {account.profile.legalLastName}</CardTitle>
          <p className="text-sm text-slate-500">
            {account.membership?.memberNumber ?? "Member number pending"} ·{" "}
            {account.membership?.status.replaceAll("_", " ") ?? "membership pending"}
          </p>
        </CardHeader>
        <CardContent>
          {!emailVerified ? (
            <div className="mb-6">
              <Alert tone="warning">
                Your email address is not verified. Verify it to support account
                recovery.
              </Alert>
              <div className="mt-3">
                <VerificationNotice email={actor.email} />
              </div>
            </div>
          ) : null}
          <AccountForm
            profile={account.profile}
            phone={account.phone}
            directory={account.directory}
            directoryPreferences={account.directoryPreferences}
            notificationPreferences={account.notificationPreferences}
          />
        </CardContent>
      </Card>
    </div>
  );
}
