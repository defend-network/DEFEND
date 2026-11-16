import { NextResponse } from "next/server";
import { z } from "zod";

import {
  MAX_PASSWORD_LENGTH,
  MIN_PASSWORD_LENGTH,
  activateInvitation,
} from "@/lib/auth/invitations";

export const dynamic = "force-dynamic";

const bodySchema = z.object({
  token: z.string().min(1).max(512),
  name: z.string().trim().min(2).max(160),
  password: z.string().min(MIN_PASSWORD_LENGTH).max(MAX_PASSWORD_LENGTH),
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
    return NextResponse.json(
      {
        error: `Enter your name and a password between ${MIN_PASSWORD_LENGTH} and ${MAX_PASSWORD_LENGTH} characters.`,
      },
      { status: 400 },
    );
  }

  try {
    const result = await activateInvitation(parsed.data);
    return NextResponse.json({
      ok: true,
      email: result.email,
      memberNumber: result.memberNumber,
      chapterName: result.chapterName,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Invitation is unavailable.";
    return NextResponse.json({ error: message }, { status: 410 });
  }
}
