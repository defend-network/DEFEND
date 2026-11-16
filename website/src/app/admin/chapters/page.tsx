import type { Metadata } from "next";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listChaptersWithCounts } from "@/lib/chapters/admin";
import { ChapterForm, ChapterStatusForm } from "./chapter-forms";

export const metadata: Metadata = {
  title: "Chapters",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function ChaptersAdminPage() {
  const chapters = await listChaptersWithCounts();

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Chapter administration
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Chapters</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Chapter profiles, leadership assignments, member counts, and status.
          Chapter-scoped roles are assigned from System administration.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[0.8fr_1.2fr]">
        <ChapterForm />
        <div className="grid gap-4">
          {chapters.map((chapter) => (
            <Card key={chapter.id}>
              <CardHeader>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle>{chapter.name}</CardTitle>
                  <Badge variant={chapter.status === "operating" ? "green" : chapter.status === "in_development" ? "amber" : "outline"}>
                    {chapter.status.replaceAll("_", " ")}
                  </Badge>
                </div>
                <p className="text-sm text-slate-500">
                  {chapter.county}, {chapter.state} · {chapter.memberCount} assigned member{chapter.memberCount === 1 ? "" : "s"}
                </p>
              </CardHeader>
              <CardContent className="grid gap-3">
                <p className="text-sm leading-6 text-slate-600">{chapter.description || "No description."}</p>
                {chapter.leaders.length ? (
                  <p className="text-xs text-slate-500">
                    Leaders: {chapter.leaders.map((leader) => `${leader.name} (${leader.roleKey})`).join(", ")}
                  </p>
                ) : (
                  <p className="text-xs text-slate-500">No chapter-scoped leadership roles assigned.</p>
                )}
                <ChapterStatusForm chapterId={chapter.id} status={chapter.status} />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
