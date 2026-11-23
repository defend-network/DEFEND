import { desc, eq, sum } from "drizzle-orm";

import { getDb } from "@/lib/db/client";
import { recordAuditEvent } from "@/lib/audit/audit";
import { encryptPii, decryptPii } from "@/lib/security/pii";
import type { ActorContext } from "@/lib/policy/permissions";
import {
  chapterAllocations,
  chapters,
  expenses,
  membershipSubscriptions,
  memberships,
  paymentEvents,
  user,
} from "@/db/schema";

export async function listFinanceOverview() {
  const db = await getDb();
  const [subscriptions, payments, expenseRows, allocations, expenseSum] =
    await Promise.all([
      db
        .select({
          id: membershipSubscriptions.id,
          status: membershipSubscriptions.status,
          amount: membershipSubscriptions.priceId,
          memberName: user.name,
          memberEmail: user.email,
          currentPeriodEnd: membershipSubscriptions.currentPeriodEnd,
        })
        .from(membershipSubscriptions)
        .innerJoin(memberships, eq(membershipSubscriptions.membershipId, memberships.id))
        .innerJoin(user, eq(memberships.userId, user.id))
        .orderBy(desc(membershipSubscriptions.updatedAt))
        .limit(100),
      db.select().from(paymentEvents).orderBy(desc(paymentEvents.occurredAt)).limit(50),
      db.select().from(expenses).orderBy(desc(expenses.incurredAt)).limit(50),
      db
        .select({
          id: chapterAllocations.id,
          chapterName: chapters.name,
          sourceType: chapterAllocations.sourceType,
          amountCents: chapterAllocations.amountCents,
          period: chapterAllocations.period,
          createdAt: chapterAllocations.createdAt,
        })
        .from(chapterAllocations)
        .leftJoin(chapters, eq(chapterAllocations.chapterId, chapters.id))
        .orderBy(desc(chapterAllocations.createdAt))
        .limit(50),
      db.select({ value: sum(expenses.amountCents) }).from(expenses),
    ]);

  return {
    subscriptions,
    payments,
    expenses: expenseRows,
    allocations,
    totalExpensesCents: Number(expenseSum[0]?.value ?? 0),
  };
}

export async function listChaptersBasic() {
  const db = await getDb();
  return db.select({ id: chapters.id, name: chapters.name }).from(chapters);
}

export async function createExpense(input: {
  actor: ActorContext;
  chapterId?: string | null;
  category: string;
  vendor: string;
  amountCents: number;
  incurredAt: Date;
  paidBy?: string;
  notes?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  if (input.amountCents <= 0) return { ok: false as const, error: "Enter a positive amount." };
  const db = await getDb();
  const id = `expense_${crypto.randomUUID()}`;
  await db.insert(expenses).values({
    id,
    chapterId: input.chapterId || null,
    category: input.category,
    vendor: input.vendor.trim(),
    amountCents: Math.round(input.amountCents),
    incurredAt: input.incurredAt,
    paidBy: input.paidBy?.trim() || null,
    status: "recorded",
    notesEncrypted: input.notes?.trim() ? await encryptPii(input.notes.trim()) : null,
    createdAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "finance.expense.create",
    targetType: "expense",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { category: input.category, amountCents: input.amountCents },
  });
  return { ok: true as const, id };
}

export async function createAllocation(input: {
  actor: ActorContext;
  chapterId: string;
  sourceType: string;
  amountCents: number;
  period?: string;
  notes?: string;
  requestId?: string | null;
  ipHash?: string | null;
  userAgent?: string | null;
}) {
  if (input.amountCents <= 0) return { ok: false as const, error: "Enter a positive amount." };
  const db = await getDb();
  const id = `allocation_${crypto.randomUUID()}`;
  await db.insert(chapterAllocations).values({
    id,
    chapterId: input.chapterId,
    sourceType: input.sourceType,
    amountCents: Math.round(input.amountCents),
    period: input.period?.trim() || null,
    notes: input.notes?.trim() || null,
    createdAt: new Date(),
  });
  await recordAuditEvent({
    actorUserId: input.actor.userId,
    action: "finance.allocation.create",
    targetType: "chapter_allocation",
    targetId: id,
    outcome: "success",
    requestId: input.requestId,
    ipHash: input.ipHash,
    userAgent: input.userAgent,
    metadata: { chapterId: input.chapterId, amountCents: input.amountCents },
  });
  return { ok: true as const, id };
}

export async function getExpenseNotes(expenseId: string) {
  const db = await getDb();
  const rows = await db
    .select({ notesEncrypted: expenses.notesEncrypted })
    .from(expenses)
    .where(eq(expenses.id, expenseId))
    .limit(1);
  const encoded = rows[0]?.notesEncrypted;
  return encoded ? decryptPii(encoded).catch(() => null) : null;
}
