import { NextResponse } from "next/server";

import { getEnv } from "@/lib/db/client";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const env = await getEnv();
    const result = await env.DB.prepare("SELECT 1 AS ok").first<{ ok: number }>();
    return NextResponse.json({
      ok: result?.ok === 1,
      service: "defend-website",
      environment: env.APP_ENV ?? process.env.NODE_ENV ?? "unknown",
      database: result?.ok === 1 ? "connected" : "unavailable",
      payments: env.PAYMENTS_MODE === "live" ? "live" : "test",
    });
  } catch {
    return NextResponse.json(
      {
        ok: false,
        service: "defend-website",
        database: "unavailable",
      },
      { status: 503 },
    );
  }
}
