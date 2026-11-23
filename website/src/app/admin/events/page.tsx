import type { Metadata } from "next";
import Link from "next/link";
import { format } from "date-fns";

import { AdminAccessDenied } from "@/components/admin/access-denied";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminPageActor } from "@/lib/auth/admin";
import { listAdminEvents } from "@/lib/events/events";
import { chapterIdsForPermission } from "@/lib/policy/permissions";
import { EventAdminForms } from "./event-admin-forms";

export const metadata: Metadata = {
  title: "Events",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function AdminEventsPage() {
  const { actor, allowed } = await adminPageActor("events.view");
  if (!allowed) return <AdminAccessDenied module="events" />;
  const eventRows = await listAdminEvents({
    chapterIds: chapterIdsForPermission(actor, "events.view"),
  });

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Programs and events
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Events and volunteers</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Create events and volunteer opportunities. Published events appear on
          the public events page.
        </p>
      </div>

      <EventAdminForms />

      <Card>
        <CardHeader>
          <CardTitle>Events</CardTitle>
        </CardHeader>
        <CardContent>
          {eventRows.length === 0 ? (
            <p className="text-sm text-slate-500">No events created yet.</p>
          ) : (
            <ul className="grid gap-3">
              {eventRows.map((event) => (
                <li key={event.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-control)] border border-slate-200 p-3">
                  <div>
                    <p className="font-semibold text-navy-900">{event.title}</p>
                    <p className="text-xs text-slate-500">
                      {format(event.startsAt, "MMM d, yyyy h:mm a")} ·{" "}
                      {event.locationName || "Location TBD"} ·{" "}
                      {event.capacity ? `${event.capacity} capacity` : "No capacity limit"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant={event.status === "published" ? "green" : "outline"}>
                      {event.status}
                    </Badge>
                    {event.status === "published" ? (
                      <Link
                        href={`/events/${event.slug}`}
                        className="text-sm font-semibold text-red-700 underline-offset-4 hover:underline"
                      >
                        Public page
                      </Link>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
