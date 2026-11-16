import { NextResponse } from "next/server";
import { z } from "zod";

import { getApplicationUpdate } from "@/lib/membership/applications";

export const dynamic = "force-dynamic";

const schema = z.object({ token: z.string().min(1).max(512) });

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  const result = await getApplicationUpdate(parsed.data.token);
  if (!result.ok || !result.application) {
    return NextResponse.json(
      { error: result.error || "This update link is unavailable." },
      { status: 410 },
    );
  }
  return NextResponse.json({ application: result.application });
}
