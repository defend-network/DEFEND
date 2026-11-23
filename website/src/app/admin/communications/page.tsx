import type { Metadata } from "next";
import { count, desc, eq } from "drizzle-orm";
import { format } from "date-fns";

import { AdminAccessDenied } from "@/components/admin/access-denied";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { adminPageActor } from "@/lib/auth/admin";
import { getDb } from "@/lib/db/client";
import { emailDeliveryEvents, emailOutbox, newsletterSubscribers } from "@/db/schema";

export const metadata: Metadata = {
  title: "Communications",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function CommunicationsPage() {
  const { allowed } = await adminPageActor("communications.view");
  if (!allowed) return <AdminAccessDenied module="communications" />;
  const db = await getDb();
  const [events, outbox, outboxCount, newsletterCount] = await Promise.all([
    db
      .select()
      .from(emailDeliveryEvents)
      .orderBy(desc(emailDeliveryEvents.createdAt))
      .limit(50),
    db
      .select()
      .from(emailOutbox)
      .orderBy(desc(emailOutbox.createdAt))
      .limit(20),
    db.select({ value: count() }).from(emailOutbox),
    db
      .select({ value: count() })
      .from(newsletterSubscribers)
      .where(eq(newsletterSubscribers.status, "subscribed")),
  ]);

  const transport = process.env.EMAIL_TRANSPORT || (process.env.APP_ENV === "production" ? "not_configured" : "outbox");
  const resendConfigured = Boolean(process.env.RESEND_API_KEY && process.env.EMAIL_FROM);

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Member communications
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Communications</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Transactional delivery history, template status, and consent-aware
          notification operations. No bulk distribution is enabled.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-4">
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Transport</p><CardTitle className="text-2xl">{transport}</CardTitle></CardHeader></Card>
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Resend credentials</p><CardTitle className="text-2xl">{resendConfigured ? "Configured" : "Not configured"}</CardTitle></CardHeader></Card>
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Outbox messages</p><CardTitle className="text-3xl">{outboxCount[0]?.value ?? 0}</CardTitle></CardHeader></Card>
        <Card><CardHeader><p className="text-xs font-bold uppercase tracking-[0.16em] text-slate-500">Newsletter subscribers</p><CardTitle className="text-3xl">{newsletterCount[0]?.value ?? 0}</CardTitle></CardHeader></Card>
      </div>

      <Alert tone="warning">
        Bulk email and newsletter blasts remain disabled. This page shows
        transactional delivery events only. Consent and unsubscribe controls are
        stored in member preferences and must be honored by any future bulk send.
      </Alert>

      <Card>
        <CardHeader><CardTitle>Delivery history</CardTitle></CardHeader>
        <CardContent>
          {events.length === 0 ? <p className="text-sm text-slate-500">No delivery events.</p> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[850px] text-left text-sm">
                <thead className="border-b border-slate-200 text-xs uppercase tracking-[0.12em] text-slate-500">
                  <tr><th className="px-3 py-3">Template</th><th className="px-3 py-3">Recipient</th><th className="px-3 py-3">Provider</th><th className="px-3 py-3">Status</th><th className="px-3 py-3">Time</th></tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id} className="border-b border-slate-100 last:border-0">
                      <td className="px-3 py-3 font-semibold text-navy-900">{event.templateKey}</td>
                      <td className="px-3 py-3 text-slate-600">{event.recipient}</td>
                      <td className="px-3 py-3 text-slate-600">{event.provider}</td>
                      <td className="px-3 py-3"><Badge variant={event.status === "sent" || event.status === "outbox" ? "green" : "amber"}>{event.status}</Badge></td>
                      <td className="px-3 py-3 text-slate-600">{format(event.createdAt, "MMM d, yyyy h:mm a")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {process.env.APP_ENV !== "production" ? (
        <Card>
          <CardHeader><CardTitle>Development outbox</CardTitle></CardHeader>
          <CardContent>
            {outbox.length === 0 ? <p className="text-sm text-slate-500">No outbox messages.</p> : (
              <ul className="grid gap-3">
                {outbox.map((message) => (
                  <li key={message.id} className="rounded-[var(--radius-control)] border border-slate-200 p-3">
                    <p className="font-semibold text-navy-900">{message.subject}</p>
                    <p className="text-xs text-slate-500">{message.recipient} · {message.templateKey} · {format(message.createdAt, "MMM d, yyyy h:mm a")}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
