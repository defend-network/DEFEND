import { NextResponse } from "next/server";
import { z } from "zod";

import { getInvitationStatus } from "@/lib/auth/invitations";

export const dynamic = "force-dynamic";

const bodySchema = z.object({
  token: z.string().min(1).max(512),
});

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }

  const parsed = bodySchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }

  try {
    const status = await getInvitationStatus(parsed.data.token);
    if (!status) {
      return NextResponse.json({ state: "invalid" });
    }
    return NextResponse.json({
      state: status.state,
      email: status.email,
      expiresAt: status.expiresAt?.toISOString(),
    });
  } catch {
    return NextResponse.json(
      { error: "Invitation service is unavailable." },
      { status: 503 },
    );
  }
}
