import type { Metadata } from "next";
import { and, count, desc, eq, inArray } from "drizzle-orm";
import { format } from "date-fns";

import Link from "next/link";

import { AdminAccessDenied } from "@/components/admin/access-denied";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminPageAnyPermission } from "@/lib/auth/admin";
import { getDb } from "@/lib/db/client";
import { can, chapterIdsForPermission } from "@/lib/policy/permissions";
import {
  chapters,
  contactMessages,
  membershipApplications,
  memberships,
} from "@/db/schema";

export const metadata: Metadata = {
  title: "Admin Overview",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

function dateLabel(value: Date | null): string {
  return value ? format(value, "MMM d, yyyy h:mm a") : "â€”";
}

export default async function AdminPage() {
  const { actor, allowed } = await adminPageAnyPermission();
  if (!allowed) return <AdminAccessDenied module="admin overview" />;
  const canViewMessages = can(actor, "communications.view");
  const applicationScope = chapterIdsForPermission(actor, "applications.view");
  const memberScope = chapterIdsForPermission(actor, "members.view");
  const chapterScope = chapterIdsForPermission(actor, "chapters.view");
  let data:
    | {
        counts: {
          applications: number;
          members: number;
          messages: number;
          chapters: number;
        };
        applications: Array<{
          id: string;
          applicationNumber: string;
          legalName: string;
          email: string;
          status: string;
          submittedAt: Date;
        }>;
        messages: Array<{
          id: string;
          name: string;
          email: string;
          subject: string;
          createdAt: Date;
        }>;
        chapterName: string;
      }
    | undefined;
  let error = false;

  try {
    const db = await getDb();
    const applicationConditions = [
      inArray(membershipApplications.status, [
        "submitted",
        "under_review",
        "needs_info",
      ]),
    ];
    if (applicationScope !== "all") {
      applicationConditions.push(
        applicationScope.length
          ? inArray(membershipApplications.desiredChapterId, applicationScope)
          : eq(membershipApplications.id, "__none__"),
      );
    }
    const memberConditions = [eq(memberships.status, "active")];
    if (memberScope !== "all") {
      memberConditions.push(
        memberScope.length
          ? inArray(memberships.chapterId, memberScope)
          : eq(memberships.id, "__none__"),
      );
    }
    const chapterCondition =
      chapterScope === "all"
        ? undefined
        : chapterScope.length
          ? inArray(chapters.id, chapterScope)
          : eq(chapters.id, "__none__");

    const [applicationCount, memberCount, messageCount, chapterCount] =
      await Promise.all([
        db
          .select({ value: count() })
          .from(membershipApplications)
          .where(and(...applicationConditions)),
        db
          .select({ value: count() })
          .from(memberships)
          .where(and(...memberConditions)),
        canViewMessages
          ? db.select({ value: count() }).from(contactMessages)
          : Promise.resolve([{ value: 0 }]),
        db
          .select({ value: count() })
          .from(chapters)
          .where(chapterCondition),
      ]);

    const applications = await db
      .select({
        id: membershipApplications.id,
        applicationNumber: membershipApplications.applicationNumber,
        legalName: membershipApplications.legalName,
        email: membershipApplications.email,
        status: membershipApplications.status,
        submittedAt: membershipApplications.submittedAt,
      })
      .from(membershipApplications)
      .where(and(...applicationConditions))
      .orderBy(desc(membershipApplications.submittedAt))
      .limit(8);

    const messages = canViewMessages
      ? await db
          .select({
            id: contactMessages.id,
            name: contactMessages.name,
            email: contactMessages.email,
            subject: contactMessages.subject,
            createdAt: contactMessages.createdAt,
          })
          .from(contactMessages)
          .orderBy(desc(contactMessages.createdAt))
          .limit(5)
      : [];

    const chapter = await db
      .select({ name: chapters.name })
      .from(chapters)
      .where(
        chapterScope !== "all" && chapterScope.length
          ? inArray(chapters.id, chapterScope)
          : eq(chapters.id, "chapter_pasco"),
      )
      .limit(1);

    data = {
      counts: {
        applications: applicationCount[0]?.value ?? 0,
        members: memberCount[0]?.value ?? 0,
        messages: messageCount[0]?.value ?? 0,
        chapters: chapterCount[0]?.value ?? 0,
      },
      applications,
      messages,
      chapterName: chapter[0]?.name ?? "Pasco County",
    };
  } catch {
    error = true;
  }

  if (error || !data) {
    return (
      <Alert tone="error">
        The administrative database is unavailable. Check the Cloudflare D1
        binding and local migration state.
      </Alert>
    );
  }

  return (
    <div className="grid gap-8">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Overview
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Administrative overview</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Live counts from the DEFEND database. No placeholder metrics.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button asChild size="sm">
            <Link href="/admin/applications">Review applications</Link>
          </Button>
          <Button asChild variant="secondary" size="sm">
            <Link href="/admin/members">Manage members</Link>
          </Button>
          <Button asChild variant="secondary" size="sm">
            <Link href="/admin/events">Events and volunteers</Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          ["Pending applications", data.counts.applications],
          ["Active members", data.counts.members],
          ["Contact messages", data.counts.messages],
          ["Chapters", data.counts.chapters],
        ].map(([label, value]) => (
          <Card key={String(label)}>
            <CardHeader>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">
                {label}
              </p>
              <CardTitle className="text-3xl">{value}</CardTitle>
            </CardHeader>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Recent applications</CardTitle>
            <p className="mt-1 text-sm text-slate-500">
              Review and decision actions are available to authorized reviewers.
            </p>
          </div>
          <Badge variant="amber">Manual review required</Badge>
        </CardHeader>
        <CardContent>
          {data.applications.length === 0 ? (
            <p className="text-sm text-slate-500">
              No applications have been submitted yet.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-[0.12em] text-slate-500">
                  <tr>
                    <th className="px-2 py-3">Application</th>
                    <th className="px-2 py-3">Applicant</th>
                    <th className="px-2 py-3">Status</th>
                    <th className="px-2 py-3">Submitted</th>
                  </tr>
                </thead>
                <tbody>
                  {data.applications.map((application) => (
                    <tr
                      key={application.id}
                      className="border-b border-slate-100 last:border-0"
                    >
                      <td className="px-2 py-3 font-mono text-xs">
                        {application.applicationNumber}
                      </td>
                      <td className="px-2 py-3">
                        <p className="font-semibold text-navy-900">
                          {application.legalName}
                        </p>
                        <p className="text-xs text-slate-500">
                          {application.email}
                        </p>
                      </td>
                      <td className="px-2 py-3">
                        <Badge variant="amber">
                          {application.status.replaceAll("_", " ")}
                        </Badge>
                      </td>
                      <td className="px-2 py-3 text-slate-600">
                        {dateLabel(application.submittedAt)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <div className={`grid gap-5 ${canViewMessages ? "lg:grid-cols-2" : ""}`}>
        {canViewMessages ? (
          <Card>
            <CardHeader>
              <CardTitle>Recent contact messages</CardTitle>
            </CardHeader>
            <CardContent>
              {data.messages.length === 0 ? (
                <p className="text-sm text-slate-500">No messages yet.</p>
              ) : (
                <ul className="grid gap-3">
                  {data.messages.map((message) => (
                    <li
                      key={message.id}
                      className="rounded-[var(--radius-control)] border border-slate-200 p-3"
                    >
                      <p className="text-sm font-semibold text-navy-900">
                        {message.subject}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {message.name} Â· {message.email} Â·{" "}
                        {dateLabel(message.createdAt)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>Founding chapter</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-lg font-semibold text-navy-900">
              {data.chapterName}
            </p>
            <Badge variant="amber" className="mt-2">
              In development
            </Badge>
            <p className="mt-3 text-sm leading-6 text-slate-600">
              The chapter is not operational. Do not change this label without
              verified evidence of an active chapter.
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
