import type { Metadata } from "next";
import { count, desc, eq } from "drizzle-orm";
import { format } from "date-fns";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getDb } from "@/lib/db/client";
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
  return value ? format(value, "MMM d, yyyy h:mm a") : "—";
}

export default async function AdminPage() {
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
    const [applicationCount, memberCount, messageCount, chapterCount] =
      await Promise.all([
        db
          .select({ value: count() })
          .from(membershipApplications)
          .where(eq(membershipApplications.status, "submitted")),
        db
          .select({ value: count() })
          .from(memberships)
          .where(eq(memberships.status, "active")),
        db.select({ value: count() }).from(contactMessages),
        db.select({ value: count() }).from(chapters),
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
      .orderBy(desc(membershipApplications.submittedAt))
      .limit(8);

    const messages = await db
      .select({
        id: contactMessages.id,
        name: contactMessages.name,
        email: contactMessages.email,
        subject: contactMessages.subject,
        createdAt: contactMessages.createdAt,
      })
      .from(contactMessages)
      .orderBy(desc(contactMessages.createdAt))
      .limit(5);

    const chapter = await db
      .select({ name: chapters.name })
      .from(chapters)
      .where(eq(chapters.id, "chapter_pasco"))
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
              Read-only foundation view. Review and decision actions are the next
              milestone.
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

      <div className="grid gap-5 lg:grid-cols-2">
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
                      {message.name} · {message.email} ·{" "}
                      {dateLabel(message.createdAt)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

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
