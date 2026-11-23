import type { Metadata } from "next";
import Link from "next/link";
import { eq } from "drizzle-orm";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { chapters, memberProfiles, memberships } from "@/db/schema";

export const metadata: Metadata = {
  title: "Member Dashboard",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

export default async function MembersPage() {
  const actor = await getActor();
  if (!actor) return null;

  let profile:
    | {
        preferredName: string | null;
        legalFirstName: string;
        legalLastName: string;
        chapterId: string | null;
        status: string;
      }
    | undefined;
  let membership:
    | {
        memberNumber: string;
        status: string;
        chapterId: string | null;
      }
    | undefined;
  let chapterName: string | undefined;
  let databaseError = false;

  try {
    const db = await getDb();
    const profileRows = await db
      .select({
        preferredName: memberProfiles.preferredName,
        legalFirstName: memberProfiles.legalFirstName,
        legalLastName: memberProfiles.legalLastName,
        chapterId: memberProfiles.chapterId,
        status: memberProfiles.status,
      })
      .from(memberProfiles)
      .where(eq(memberProfiles.userId, actor.userId))
      .limit(1);
    profile = profileRows[0];

    const membershipRows = await db
      .select({
        memberNumber: memberships.memberNumber,
        status: memberships.status,
        chapterId: memberships.chapterId,
      })
      .from(memberships)
      .where(eq(memberships.userId, actor.userId))
      .limit(1);
    membership = membershipRows[0];

    const chapterId = membership?.chapterId ?? profile?.chapterId;
    if (chapterId) {
      const chapterRows = await db
        .select({ name: chapters.name })
        .from(chapters)
        .where(eq(chapters.id, chapterId))
        .limit(1);
      chapterName = chapterRows[0]?.name;
    }
  } catch {
    databaseError = true;
  }

  const displayName =
    profile?.preferredName ||
    (profile ? `${profile.legalFirstName} ${profile.legalLastName}` : actor.displayName);

  return (
    <div className="grid gap-8">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Member portal
        </p>
        <h1 className="mt-3 text-3xl font-semibold sm:text-4xl">
          Welcome, {displayName}.
        </h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Account: {actor.email}
        </p>
      </div>

      {databaseError ? (
        <Alert tone="error">
          The member database is temporarily unavailable. Please try again later.
        </Alert>
      ) : null}

      {membership?.status === "free_access" ? (
        <Alert tone="info">
          You are signed in with a Free account.{" "}
          <Link href="/membership" className="font-semibold underline">
            Compare paid tiers
          </Link>{" "}
          to unlock workshops, gym eligibility, volunteering, and the member
          directory. Existing free accounts will not create a second account;
          upgrade payment activation is still being completed.
        </Alert>
      ) : null}

      <div className="grid gap-5 md:grid-cols-3">
        <Card>
          <CardHeader>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
              Membership status
            </p>
            <CardTitle className="capitalize">
              {membership ? statusLabel(membership.status) : "Not yet assigned"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-slate-600">
              {membership
                ? `Member number ${membership.memberNumber}`
                : "Your membership record will appear after an administrator completes approval and onboarding."}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
              Chapter
            </p>
            <CardTitle>{chapterName ?? "Pasco County"}</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant="amber">In development</Badge>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              The Pasco County founding chapter is being organized.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
              Dues
            </p>
            <CardTitle>Not active</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm leading-6 text-slate-600">
              Online billing is not enabled. Approved founding members may use
              the portal before live billing begins.
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Your account</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 text-sm text-slate-600">
            <p>
              <strong className="text-navy-900">Name:</strong> {displayName}
            </p>
            <p>
              <strong className="text-navy-900">Email:</strong> {actor.email}
            </p>
            <p>
              <strong className="text-navy-900">Profile status:</strong>{" "}
              {profile ? statusLabel(profile.status) : "pending setup"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>
              {membership?.status === "free_access"
                ? "Free account access"
                : "Member tools"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-2 text-sm leading-6 text-slate-600">
              {membership?.status === "free_access" ? (
                <>
                  <li>Organizational announcements</li>
                  <li>Eligible public events</li>
                  <li>Paid features require Standard membership or higher</li>
                </>
              ) : (
                <>
                  <li>Profile and notification preferences</li>
                  <li>Digital membership card with secure check-in</li>
                  <li>Opt-in member directory</li>
                  <li>Event and volunteer registration</li>
                  <li>Billing management when live payments are approved</li>
                </>
              )}
            </ul>
            <div className="mt-5">
              <Button asChild variant="secondary" size="sm">
                <Link href={membership?.status === "free_access" ? "/membership" : "/contact"}>
                  {membership?.status === "free_access"
                    ? "Compare membership tiers"
                    : "Contact DEFEND"}
                </Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
