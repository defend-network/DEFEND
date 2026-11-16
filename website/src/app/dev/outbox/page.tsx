import type { Metadata } from "next";
import { desc } from "drizzle-orm";
import { notFound, redirect } from "next/navigation";

import { Alert } from "@/components/ui/alert";
import { Container } from "@/components/ui/section";
import { getActor } from "@/lib/auth/session";
import { getDb } from "@/lib/db/client";
import { emailOutbox } from "@/db/schema";

export const metadata: Metadata = {
  title: "Development Email Outbox",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function DevOutboxPage() {
  if (process.env.APP_ENV === "production") notFound();
  const actor = await getActor();
  if (!actor) redirect("/login?next=/dev/outbox");
  if (!actor.roles.some((role) => role.roleKey === "owner")) {
    return (
      <Container className="py-12">
        <Alert tone="error">Owner access is required.</Alert>
      </Container>
    );
  }

  const db = await getDb();
  const messages = await db
    .select()
    .from(emailOutbox)
    .orderBy(desc(emailOutbox.createdAt))
    .limit(25);

  return (
    <Container className="py-10">
      <div className="mb-6">
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Development only
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Email outbox</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          This page exists only when `APP_ENV` is not `production`. It contains
          activation and password-reset links for local verification. Never
          enable the outbox transport in production.
        </p>
      </div>
      <div className="grid gap-4">
        {messages.length === 0 ? (
          <Alert tone="info">No development emails have been generated.</Alert>
        ) : (
          messages.map((message) => (
            <details key={message.id} className="rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
              <summary className="cursor-pointer text-sm font-semibold text-navy-900">
                {message.subject} → {message.recipient}
              </summary>
              <p className="mt-2 text-xs text-slate-500">
                {message.templateKey} · {message.createdAt.toLocaleString()}
              </p>
              <pre className="mt-3 whitespace-pre-wrap rounded-[var(--radius-control)] bg-paper p-4 text-xs text-slate-700">
                {message.textBody}
              </pre>
            </details>
          ))
        )}
      </div>
    </Container>
  );
}
