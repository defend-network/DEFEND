import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { format } from "date-fns";

import { AdminAccessDenied } from "@/components/admin/access-denied";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getActor } from "@/lib/auth/session";
import { can } from "@/lib/policy/permissions";
import { getApplicationDetail } from "@/lib/membership/applications";
import { ApplicationReviewPanel } from "./review-panel";

export const metadata: Metadata = {
  title: "Application Detail",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

function parseList(value: string): string[] {
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch {
    return [];
  }
}

function badgeVariant(status: string) {
  if (status === "approved" || status === "activated") return "green" as const;
  if (status === "denied") return "red" as const;
  if (status === "needs_info") return "amber" as const;
  return "outline" as const;
}

export default async function ApplicationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const detail = await getApplicationDetail(id);
  if (!detail) notFound();

  const actor = await getActor();
  const application = detail.application;
  const allowed = actor
    ? can(actor, "applications.view", {
        chapterId: application.desiredChapterId,
      })
    : false;
  if (!actor || !allowed) {
    return <AdminAccessDenied module="applications" />;
  }
  const canReview = can(actor, "applications.review", {
    chapterId: application.desiredChapterId,
  });
  const chapterNames = new Map(detail.chapters.map((chapter) => [chapter.id, chapter.name]));
  const interests = parseList(application.interestsJson);
  const skills = parseList(application.skillsJson);
  const volunteer = parseList(application.volunteerInterestsJson);
  const programs = parseList(application.programInterestsJson);

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Application review
          </p>
          <h1 className="mt-3 text-3xl font-semibold">
            {application.preferredName || application.legalName}
          </h1>
          <p className="mt-2 font-mono text-sm text-slate-500">
            {application.applicationNumber}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant={badgeVariant(application.status)}>
            {application.status.replaceAll("_", " ")}
          </Badge>
          <Button asChild variant="secondary" size="sm">
            <Link href="/admin/applications">Back to queue</Link>
          </Button>
        </div>
      </div>

      {!canReview ? (
        <Alert tone="warning">
          Review actions require MFA. Enroll and verify an authenticator at{" "}
          <Link href="/admin/security" className="font-semibold underline">
            Admin security
          </Link>
          . Read-only data is still visible.
        </Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="grid gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Applicant information</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm text-slate-600 sm:grid-cols-2">
              <p><strong className="text-navy-900">Legal name:</strong> {application.legalName}</p>
              <p><strong className="text-navy-900">Preferred name:</strong> {application.preferredName || "—"}</p>
              <p><strong className="text-navy-900">Email:</strong> {application.email}</p>
              <p><strong className="text-navy-900">Phone:</strong> {application.phone || "—"}</p>
              <p><strong className="text-navy-900">City:</strong> {application.city || "—"}</p>
              <p><strong className="text-navy-900">State / ZIP:</strong> {[application.state, application.postalCode].filter(Boolean).join(" ") || "—"}</p>
              <p><strong className="text-navy-900">Desired chapter:</strong> {application.desiredChapterId ? chapterNames.get(application.desiredChapterId) ?? application.desiredChapterId : "—"}</p>
              <p><strong className="text-navy-900">Requested tier:</strong> {application.requestedTierKey ? application.requestedTierKey.replaceAll("_", " ") : "Not recorded"}</p>
              <p><strong className="text-navy-900">Recommended chapter:</strong> {application.recommendedChapterId ? chapterNames.get(application.recommendedChapterId) ?? application.recommendedChapterId : "—"}</p>
              <p><strong className="text-navy-900">Submitted:</strong> {format(application.submittedAt, "MMM d, yyyy h:mm a")}</p>
              <p><strong className="text-navy-900">Reviewed:</strong> {application.reviewedAt ? format(application.reviewedAt, "MMM d, yyyy h:mm a") : "—"}</p>
              <p><strong className="text-navy-900">Notification:</strong> {application.notificationStatus}</p>
              <p><strong className="text-navy-900">Referral source:</strong> {application.referralSource || "—"}</p>
              <p><strong className="text-navy-900">UTM source / campaign:</strong> {[application.utmSource, application.utmCampaign].filter(Boolean).join(" / ") || "—"}</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Interests and experience</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 text-sm text-slate-600">
              <div>
                <p className="font-semibold text-navy-900">Interests</p>
                <p>{interests.length ? interests.join(", ") : "—"}</p>
              </div>
              <div>
                <p className="font-semibold text-navy-900">Skills / profession</p>
                <p>{skills.length ? skills.join(", ") : "—"}</p>
              </div>
              <div>
                <p className="font-semibold text-navy-900">Volunteer interests</p>
                <p>{volunteer.length ? volunteer.join(", ") : "—"}</p>
              </div>
              <div>
                <p className="font-semibold text-navy-900">Program interests</p>
                <p>{programs.length ? programs.join(", ") : "—"}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Review history</CardTitle>
            </CardHeader>
            <CardContent>
              {detail.reviews.length === 0 ? (
                <p className="text-sm text-slate-500">No review actions yet.</p>
              ) : (
                <ul className="grid gap-3 text-sm">
                  {detail.reviews.map((review) => (
                    <li key={review.id} className="rounded-[var(--radius-control)] border border-slate-200 p-3">
                      <p className="font-semibold capitalize text-navy-900">
                        {review.action.replaceAll("_", " ")}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {format(review.createdAt, "MMM d, yyyy h:mm a")} · reviewer {review.reviewerId}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="grid gap-6">
          {application.infoRequest ? (
            <Alert tone="info">
              <strong>Latest information request:</strong> {application.infoRequest}
            </Alert>
          ) : null}
          {application.decisionNotes ? (
            <Alert tone="info">
              <strong>Decision notes:</strong> {application.decisionNotes}
            </Alert>
          ) : null}
          {canReview ? (
            <ApplicationReviewPanel applicationId={application.id} status={application.status} />
          ) : null}
        </div>
      </div>
    </div>
  );
}
