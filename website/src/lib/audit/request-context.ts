import { headers } from "next/headers";

import { hashClientIp } from "@/lib/audit/audit";

export async function requestAuditContext() {
  const headerStore = await headers();
  const ip =
    headerStore.get("cf-connecting-ip") ??
    headerStore.get("x-forwarded-for")?.split(",")[0]?.trim() ??
    null;
  return {
    requestId:
      headerStore.get("x-request-id")?.slice(0, 200) ??
      `req_${crypto.randomUUID()}`,
    ipHash: await hashClientIp(ip),
    userAgent: headerStore.get("user-agent")?.slice(0, 300) ?? null,
  };
}
