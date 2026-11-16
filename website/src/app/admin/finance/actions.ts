"use server";

import { revalidatePath } from "next/cache";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { can } from "@/lib/policy/permissions";
import { createAllocation, createExpense } from "@/lib/finance/finance";
import type { FinanceActionState } from "./action-state";

async function financeActor() {
  const actor = await getActor();
  if (!actor || !can(actor, "finance.manage")) {
    throw new Error("MFA-verified finance access is required.");
  }
  return actor;
}

function value(formData: FormData, name: string): string {
  return String(formData.get(name) ?? "").trim();
}

export async function createExpenseAction(
  _previous: FinanceActionState,
  formData: FormData,
): Promise<FinanceActionState> {
  try {
    const actor = await financeActor();
    const vendor = value(formData, "vendor");
    const amount = Number(formData.get("amountDollars") ?? "");
    const incurredAt = new Date(value(formData, "incurredAt"));
    if (!vendor || !Number.isFinite(amount) || amount <= 0 || Number.isNaN(incurredAt.getTime())) {
      return { status: "error", message: "Enter a vendor, positive amount, and date." };
    }
    const context = await requestAuditContext();
    const result = await createExpense({
      actor,
      chapterId: value(formData, "chapterId") || null,
      category: value(formData, "category") || "general",
      vendor,
      amountCents: Math.round(amount * 100),
      incurredAt,
      paidBy: value(formData, "paidBy"),
      notes: value(formData, "notes"),
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/finance");
    return { status: "success", message: "Expense recorded." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Expense creation failed." };
  }
}

export async function createAllocationAction(
  _previous: FinanceActionState,
  formData: FormData,
): Promise<FinanceActionState> {
  try {
    const actor = await financeActor();
    const chapterId = value(formData, "chapterId");
    const amount = Number(formData.get("amountDollars") ?? "");
    if (!chapterId || !Number.isFinite(amount) || amount <= 0) {
      return { status: "error", message: "Choose a chapter and enter a positive amount." };
    }
    const context = await requestAuditContext();
    const result = await createAllocation({
      actor,
      chapterId,
      sourceType: value(formData, "sourceType") || "manual",
      amountCents: Math.round(amount * 100),
      period: value(formData, "period"),
      notes: value(formData, "notes"),
      ...context,
    });
    if (!result.ok) return { status: "error", message: result.error };
    revalidatePath("/admin/finance");
    return { status: "success", message: "Chapter allocation recorded." };
  } catch (error) {
    return { status: "error", message: error instanceof Error ? error.message : "Allocation creation failed." };
  }
}
