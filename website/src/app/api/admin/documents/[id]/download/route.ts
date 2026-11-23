import { NextResponse } from "next/server";

import { getActor } from "@/lib/auth/session";
import { requestAuditContext } from "@/lib/audit/request-context";
import { recordAuditEvent } from "@/lib/audit/audit";
import { getEnv } from "@/lib/db/client";
import {
  canReadDocument,
  getDocumentForDownload,
} from "@/lib/documents/documents";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const actor = await getActor();
  if (!actor) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const { id } = await params;
  const document = await getDocumentForDownload(id);
  if (!document) {
    return NextResponse.json({ error: "Document not found." }, { status: 404 });
  }
  if (!canReadDocument(actor, document)) {
    return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  }

  const env = await getEnv();
  const object = await env.DOCUMENTS.get(document.r2Key);
  if (!object) {
    return NextResponse.json({ error: "Document file not found." }, { status: 404 });
  }

  const context = await requestAuditContext();
  await recordAuditEvent({
    actorUserId: actor.userId,
    action: "document.download",
    targetType: "document",
    targetId: document.id,
    outcome: "success",
    requestId: context.requestId,
    ipHash: context.ipHash,
    userAgent: context.userAgent,
    metadata: { visibility: document.visibility },
  });

  return new Response(object.body as unknown as BodyInit, {
    headers: {
      "Content-Type": document.mimeType,
      "Content-Disposition": `attachment; filename="${document.filename}"`,
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
