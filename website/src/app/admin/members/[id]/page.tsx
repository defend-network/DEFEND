import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { format } from "date-fns";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getActor } from "@/lib/auth/session";
import { can } from "@/lib/policy/permissions";
import { getMemberDetail } from "@/lib/membership/members";
import {
  ChapterAssignmentForm,
  MemberStatusForm,
} from "./member-actions";

export const metadata: Metadata = {
  title: "Member Detail",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function MemberDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const detail = await getMemberDetail(id);
  if (!detail) notFound();

  const actor = await getActor();
  const canManage = actor ? can(actor, "members.manage") : false;
  const profile = detail.profile;
  const membership = detail.membership;

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Member administration
          </p>
          <h1 className="mt-3 text-3xl font-semibold">
            {profile?.preferredName || detail.user.name}
          </h1>
          <p className="mt-2 font-mono text-sm text-slate-500">
            {membership.memberNumber}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={membership.status === "active" ? "green" : "amber"}>
            {membership.status.replaceAll("_", " ")}
          </Badge>
          <Button asChild variant="secondary" size="sm">
            <Link href="/admin/members">Back to members</Link>
          </Button>
        </div>
      </div>

      {!canManage ? (
        <Alert tone="warning">
          Member-management actions require MFA. Read-only access is shown.
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="grid gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Member record</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm text-slate-600 sm:grid-cols-2">
              <p><strong className="text-navy-900">Name:</strong> {detail.user.name}</p>
              <p><strong className="text-navy-900">Email:</strong> {detail.user.email}</p>
              <p><strong className="text-navy-900">Email verified:</strong> {detail.user.emailVerified ? "Yes" : "No"}</p>
              <p><strong className="text-navy-900">MFA enabled:</strong> {detail.user.twoFactorEnabled ? "Yes" : "No"}</p>
              <p><strong className="text-navy-900">Phone:</strong> {detail.phone || "—"}</p>
              <p><strong className="text-navy-900">City / state:</strong> {[profile?.city, profile?.state].filter(Boolean).join(", ") || "—"}</p>
              <p><strong className="text-navy-900">Chapter:</strong> {detail.chapterName ?? "—"}</p>
              <p><strong className="text-navy-900">Member since:</strong> {membership.joinedAt ? format(membership.joinedAt, "MMM d, yyyy") : "—"}</p>
              <p><strong className="text-navy-900">Membership standing:</strong> {membership.status.replaceAll("_", " ")}</p>
              <p><strong className="text-navy-900">Dues status:</strong> {membership.duesStatus.replaceAll("_", " ")}</p>
              <p><strong className="text-navy-900">Account created:</strong> {format(detail.user.createdAt, "MMM d, yyyy h:mm a")}</p>
              <p><strong className="text-navy-900">Application:</strong> {membership.applicationId ?? "—"}</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Status history</CardTitle>
            </CardHeader>
            <CardContent>
              {detail.history.length === 0 ? (
                <p className="text-sm text-slate-500">No history yet.</p>
              ) : (
                <ul className="grid gap-3 text-sm">
                  {detail.history.map((entry) => (
                    <li key={entry.id} className="rounded-[var(--radius-control)] border border-slate-200 p-3">
                      <p className="font-semibold text-navy-900">
                        {entry.fromStatus ? `${entry.fromStatus} → ` : ""}
                        {entry.toStatus}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {format(entry.createdAt, "MMM d, yyyy h:mm a")} · {entry.reason ?? "—"}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Role assignments</CardTitle>
            </CardHeader>
            <CardContent>
              {detail.roleAssignments.length === 0 ? (
                <p className="text-sm text-slate-500">No explicit role assignments.</p>
              ) : (
                <ul className="grid gap-2 text-sm">
                  {detail.roleAssignments.map((role) => (
                    <li key={role.id} className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">{role.roleKey}</Badge>
                      <span className="text-slate-600">
                        {role.scopeType}{role.scopeId ? ` · ${role.scopeId}` : ""}
                      </span>
                      {role.revokedAt ? <Badge variant="red">revoked</Badge> : null}
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6">
          {canManage ? (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Update standing</CardTitle>
                </CardHeader>
                <CardContent>
                  <MemberStatusForm
                    userId={detail.user.id}
                    currentStatus={membership.status}
                  />
                </CardContent>
              </Card>
              <Card>
                <CardHeader>
                  <CardTitle>Assign chapter</CardTitle>
                </CardHeader>
                <CardContent>
                  <ChapterAssignmentForm
                    userId={detail.user.id}
                    currentChapterId={membership.chapterId}
                    chapters={detail.chapters}
                  />
                </CardContent>
              </Card>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
