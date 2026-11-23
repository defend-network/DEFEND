import { NextResponse } from "next/server";

import { getActor } from "@/lib/auth/session";
import { getEnv } from "@/lib/db/client";
import {
  canReadDocument,
  getDocumentForDownload,
} from "@/lib/documents/documents";

export const dynamic = "force-dynamic";

const inlineTypes = new Set(["application/pdf", "image/png", "image/jpeg", "image/webp"]);

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const actor = await getActor();
  if (!actor) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id } = await params;
  const document = await getDocumentForDownload(id);
  if (!document) return NextResponse.json({ error: "Document not found." }, { status: 404 });
  if (!canReadDocument(actor, document)) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }
  if (!inlineTypes.has(document.mimeType)) {
    return NextResponse.json({ error: "Preview is not available for this file type." }, { status: 415 });
  }
  const env = await getEnv();
  const object = await env.DOCUMENTS.get(document.r2Key);
  if (!object) return NextResponse.json({ error: "Document file not found." }, { status: 404 });
  return new Response(object.body as unknown as BodyInit, {
    headers: {
      "Content-Type": document.mimeType,
      "Content-Disposition": `inline; filename="${document.filename}"`,
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
