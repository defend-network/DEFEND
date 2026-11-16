import type { Metadata } from "next";
import Link from "next/link";
import { format } from "date-fns";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { listMembers } from "@/lib/membership/members";

export const metadata: Metadata = {
  title: "Members",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

const statuses = [
  "all",
  "founding_access",
  "pending_payment",
  "active",
  "grace",
  "lapsed",
  "cancelled",
  "suspended",
];

export default async function MembersAdminPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; status?: string; page?: string }>;
}) {
  const params = await searchParams;
  const query = params.q?.slice(0, 120) ?? "";
  const status = statuses.includes(params.status ?? "") ? params.status! : "all";
  const page = Math.max(Number(params.page ?? "1") || 1, 1);
  const limit = 25;
  const data = await listMembers({
    query,
    status,
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
        <h1 className="mt-3 text-3xl font-semibold">Members</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          {data.total} member record{data.total === 1 ? "" : "s"} in the current view.
          Membership standing and dues status are displayed separately.
        </p>
      </div>

      <Card>
        <CardContent className="grid gap-4 p-5">
          <div className="flex flex-wrap gap-2">
            {statuses.map((value) => (
              <Link
                key={value}
                href={`/admin/members?status=${value}${query ? `&q=${encodeURIComponent(query)}` : ""}`}
                className={`rounded-full border px-3 py-1.5 text-xs font-semibold ${
                  status === value
                    ? "border-navy-800 bg-navy-800 text-white"
                    : "border-slate-300 bg-white text-slate-600 hover:border-navy-700"
                }`}
              >
                {value === "all" ? "All" : value.replaceAll("_", " ")}
              </Link>
            ))}
          </div>
          <form action="/admin/members" className="flex flex-col gap-3 sm:flex-row">
            <input type="hidden" name="status" value={status} />
            <input
              name="q"
              defaultValue={query}
              placeholder="Search name, email, or member number"
              className="h-11 flex-1 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm outline-none focus:border-navy-700 focus:ring-2 focus:ring-navy-800/15"
            />
            <Button type="submit" variant="secondary">Search</Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="p-0">
          {data.items.length === 0 ? (
            <p className="p-6 text-sm text-slate-500">No members match this view.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-[0.12em] text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Member</th>
                    <th className="px-4 py-3">Number</th>
                    <th className="px-4 py-3">Chapter</th>
                    <th className="px-4 py-3">Standing</th>
                    <th className="px-4 py-3">Dues</th>
                    <th className="px-4 py-3">Joined</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((member) => (
                    <tr key={member.userId} className="border-b border-slate-100 last:border-0">
                      <td className="px-4 py-3">
                        <p className="font-semibold text-navy-900">
                          {member.preferredName || member.name}
                        </p>
                        <p className="text-xs text-slate-500">{member.email}</p>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">{member.memberNumber}</td>
                      <td className="px-4 py-3 text-slate-600">{member.chapterName ?? "—"}</td>
                      <td className="px-4 py-3">
                        <Badge variant={member.membershipStatus === "active" ? "green" : "amber"}>
                          {member.membershipStatus.replaceAll("_", " ")}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {member.duesStatus.replaceAll("_", " ")}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {member.joinedAt ? format(member.joinedAt, "MMM d, yyyy") : "—"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Button asChild variant="secondary" size="sm">
                          <Link href={`/admin/members/${member.userId}`}>Manage</Link>
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
          <span>Page {page} of {pages}</span>
          <div className="flex gap-2">
            {page > 1 ? (
              <Button asChild variant="secondary" size="sm">
                <Link href={`/admin/members?status=${status}&q=${encodeURIComponent(query)}&page=${page - 1}`}>Previous</Link>
              </Button>
            ) : null}
            {page < pages ? (
              <Button asChild variant="secondary" size="sm">
                <Link href={`/admin/members?status=${status}&q=${encodeURIComponent(query)}&page=${page + 1}`}>Next</Link>
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
