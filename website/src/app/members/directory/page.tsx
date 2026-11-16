import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getActor } from "@/lib/auth/session";
import { getDirectory } from "@/lib/membership/directory";

export const metadata: Metadata = {
  title: "Member Directory",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function DirectoryPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const actor = await getActor();
  if (!actor) redirect("/login?next=/members/directory");
  const params = await searchParams;
  const query = params.q?.slice(0, 120) ?? "";
  const entries = await getDirectory({ actor, query });

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Member directory
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Opt-in directory</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-600">
            Only members who opt in appear here. Each member controls which
            fields are visible. Contact information is hidden unless the member
            explicitly shares it.
          </p>
        </div>
        <Button asChild variant="secondary" size="sm">
          <Link href="/members/account">Directory settings</Link>
        </Button>
      </div>

      <Card>
        <CardContent className="p-5">
          <form action="/members/directory" className="flex flex-col gap-3 sm:flex-row">
            <input
              name="q"
              defaultValue={query}
              placeholder="Search name, profession, business, or skills"
              className="h-11 flex-1 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm outline-none focus:border-navy-700 focus:ring-2 focus:ring-navy-800/15"
            />
            <Button type="submit" variant="secondary">Search</Button>
          </form>
        </CardContent>
      </Card>

      {entries.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center">
            <h2 className="text-lg font-semibold">No visible directory entries</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">
              No member has opted in with the current search, or the directory is
              still being adopted. You can opt in and choose your visible fields
              in account settings.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {entries.map((entry) => (
            <Card key={entry.userId}>
              <CardHeader>
                <CardTitle>{entry.displayName}</CardTitle>
                {entry.chapterName ? (
                  <p className="text-sm text-slate-500">{entry.chapterName}</p>
                ) : null}
              </CardHeader>
              <CardContent className="grid gap-3 text-sm text-slate-600">
                {entry.profession ? (
                  <p><strong className="text-navy-900">Profession:</strong> {entry.profession}</p>
                ) : null}
                {entry.businessName ? (
                  <p><strong className="text-navy-900">Business:</strong> {entry.businessName}</p>
                ) : null}
                {entry.skills.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {entry.skills.map((skill) => (
                      <Badge key={skill} variant="outline">{skill}</Badge>
                    ))}
                  </div>
                ) : null}
                {entry.volunteerInterests.length ? (
                  <p className="text-xs text-slate-500">
                    Volunteer interests: {entry.volunteerInterests.join(", ")}
                  </p>
                ) : null}
                {entry.email ? (
                  <p>
                    <strong className="text-navy-900">Email:</strong>{" "}
                    <a className="text-red-700 underline-offset-4 hover:underline" href={`mailto:${entry.email}`}>
                      {entry.email}
                    </a>
                  </p>
                ) : null}
                {entry.phone ? (
                  <p><strong className="text-navy-900">Phone:</strong> {entry.phone}</p>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
