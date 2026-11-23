import type { Metadata } from "next";
import { and, desc, eq, inArray } from "drizzle-orm";

import { AdminAccessDenied } from "@/components/admin/access-denied";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminPageActor } from "@/lib/auth/admin";
import { getDb } from "@/lib/db/client";
import { chapterIdsForPermission } from "@/lib/policy/permissions";
import { events } from "@/db/schema";
import { CheckinForm } from "./checkin-form";

export const metadata: Metadata = {
  title: "Event Check-In",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function CheckinPage() {
  const { actor, allowed } = await adminPageActor("events.checkin");
  if (!allowed) return <AdminAccessDenied module="check-in" />;
  const db = await getDb();
  const chapterIds = chapterIdsForPermission(actor, "events.checkin");
  const eventRows = await db
    .select({ id: events.id, title: events.title })
    .from(events)
    .where(
      chapterIds === "all"
        ? eq(events.status, "published")
        : and(
            eq(events.status, "published"),
            chapterIds.length > 0
              ? inArray(events.chapterId, chapterIds)
              : eq(events.id, "__none__"),
          ),
    )
    .orderBy(desc(events.startsAt))
    .limit(50);

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Events
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Member check-in</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Verify a short-lived membership card token. Event check-in also
          requires an existing registration.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Verify card</CardTitle>
        </CardHeader>
        <CardContent>
          <CheckinForm events={eventRows} />
        </CardContent>
      </Card>
    </div>
  );
}
