import { NextResponse } from "next/server";
import { z } from "zod";

import { updateApplicationWithToken } from "@/lib/membership/applications";

export const dynamic = "force-dynamic";

const schema = z.object({
  token: z.string().min(1).max(512),
  email: z.string().email().max(320),
  preferredName: z.string().max(80).optional(),
  city: z.string().min(2).max(120),
  state: z.string().length(2),
  postalCode: z.string().max(20).optional(),
  interests: z.array(z.string().max(80)).max(20),
  skills: z.string().max(1000).optional(),
  volunteerInterests: z.array(z.string().max(80)).max(20),
  programInterests: z.array(z.string().max(80)).max(20),
});

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Please correct the highlighted fields." },
      { status: 400 },
    );
  }
  const result = await updateApplicationWithToken(parsed.data);
  if (!result.ok) {
    return NextResponse.json(
      { error: result.error || "Unable to update the application." },
      { status: 410 },
    );
  }
  return NextResponse.json({ ok: true });
}
