import type { Metadata } from "next";
import Link from "next/link";
import { format } from "date-fns";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listApplications } from "@/lib/membership/applications";

export const metadata: Metadata = {
  title: "Applications",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

const statuses = [
  ["all", "All"],
  ["submitted", "Submitted"],
  ["under_review", "Under review"],
  ["needs_info", "Needs information"],
  ["approved", "Approved"],
  ["denied", "Denied"],
  ["activated", "Activated"],
] as const;

function badgeVariant(status: string) {
  if (status === "approved" || status === "activated") return "green" as const;
  if (status === "denied") return "red" as const;
  if (status === "needs_info") return "amber" as const;
  return "outline" as const;
}

export default async function ApplicationsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; q?: string; page?: string }>;
}) {
  const params = await searchParams;
  const status = statuses.some(([value]) => value === params.status)
    ? (params.status as (typeof statuses)[number][0])
    : "all";
  const query = params.q?.slice(0, 120) ?? "";
  const page = Math.max(Number(params.page ?? "1") || 1, 1);
  const limit = 25;
  const data = await listApplications({
    status,
    query,
    limit,
    offset: (page - 1) * limit,
  });
  const pages = Math.max(Math.ceil(data.total / limit), 1);

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Membership operations
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Applications</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          {data.total} application{data.total === 1 ? "" : "s"} in the current view.
          Decisions are manual and recorded.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Filter and search</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex flex-wrap gap-2">
            {statuses.map(([value, label]) => (
              <Link
                key={value}
                href={`/admin/applications?status=${value}${query ? `&q=${encodeURIComponent(query)}` : ""}`}
                className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${
                  status === value
                    ? "border-navy-800 bg-navy-800 text-white"
                    : "border-slate-300 bg-white text-slate-600 hover:border-navy-700"
                }`}
              >
                {label}
              </Link>
            ))}
          </div>
          <form action="/admin/applications" className="flex flex-col gap-3 sm:flex-row">
            <input type="hidden" name="status" value={status} />
            <input
              name="q"
              defaultValue={query}
              placeholder="Search application number, name, or email"
              className="h-11 flex-1 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm outline-none focus:border-navy-700 focus:ring-2 focus:ring-navy-800/15"
            />
            <Button type="submit" variant="secondary">
              Search
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {data.items.length === 0 ? (
            <p className="p-6 text-sm text-slate-500">No applications match this view.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-[0.12em] text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Application</th>
                    <th className="px-4 py-3">Applicant</th>
                    <th className="px-4 py-3">Location</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Submitted</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((application) => (
                    <tr key={application.id} className="border-b border-slate-100 last:border-0">
                      <td className="px-4 py-3 font-mono text-xs">
                        {application.applicationNumber}
                      </td>
                      <td className="px-4 py-3">
                        <p className="font-semibold text-navy-900">
                          {application.preferredName || application.legalName}
                        </p>
                        <p className="text-xs text-slate-500">{application.email}</p>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {[application.city, application.state].filter(Boolean).join(", ") || "—"}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={badgeVariant(application.status)}>
                          {application.status.replaceAll("_", " ")}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {format(application.submittedAt, "MMM d, yyyy h:mm a")}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button asChild variant="secondary" size="sm">
                          <Link href={`/admin/applications/${application.id}`}>Review</Link>
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {pages > 1 ? (
        <div className="flex items-center justify-between text-sm text-slate-600">
          <span>
            Page {page} of {pages}
          </span>
          <div className="flex gap-2">
            {page > 1 ? (
              <Button asChild variant="secondary" size="sm">
                <Link
                  href={`/admin/applications?status=${status}&q=${encodeURIComponent(query)}&page=${page - 1}`}
                >
                  Previous
                </Link>
              </Button>
            ) : null}
            {page < pages ? (
              <Button asChild variant="secondary" size="sm">
                <Link
                  href={`/admin/applications?status=${status}&q=${encodeURIComponent(query)}&page=${page + 1}`}
                >
                  Next
                </Link>
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
