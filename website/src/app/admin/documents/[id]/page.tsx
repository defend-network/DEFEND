import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { format } from "date-fns";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getDocumentDetail } from "@/lib/documents/documents";
import {
  AddVersionForm,
  ArchiveDocumentForm,
  RestoreVersionForm,
} from "./document-detail-forms";

export const metadata: Metadata = {
  title: "Document Detail",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

function previewable(mime: string): boolean {
  return ["application/pdf", "image/png", "image/jpeg", "image/webp"].includes(mime);
}

export default async function DocumentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const detail = await getDocumentDetail(id);
  if (!detail) notFound();
  const { document, versions } = detail;

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Secure document
          </p>
          <h1 className="mt-3 text-3xl font-semibold">{document.title}</h1>
          <p className="mt-2 text-sm text-slate-500">
            {document.filename} · {(document.sizeBytes / 1024).toFixed(0)} KB · v{document.version}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={document.status === "archived" ? "red" : "green"}>{document.status}</Badge>
          <Badge variant="outline">{document.visibility}</Badge>
          <Button asChild variant="secondary" size="sm"><Link href="/admin/documents">Back to library</Link></Button>
        </div>
      </div>

      {document.status === "archived" ? (
        <Alert tone="warning">This document is archived and excluded from normal library downloads.</Alert>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <Card>
          <CardHeader><CardTitle>Preview</CardTitle></CardHeader>
          <CardContent>
            {previewable(document.mimeType) ? (
              document.mimeType === "application/pdf" ? (
                <iframe
                  src={`/api/admin/documents/${document.id}/preview`}
                  title={document.title}
                  className="h-[70vh] w-full rounded-[var(--radius-control)] border border-slate-200"
                />
              ) : (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`/api/admin/documents/${document.id}/preview`}
                  alt={document.title}
                  className="max-h-[70vh] w-auto rounded-[var(--radius-control)] border border-slate-200"
                />
              )
            ) : (
              <div className="grid gap-3">
                <p className="text-sm text-slate-600">Inline preview is not available for this file type.</p>
                <Button asChild variant="secondary" size="sm"><a href={`/api/admin/documents/${document.id}/download`}>Download file</a></Button>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="grid gap-5">
          <Card>
            <CardHeader><CardTitle>Metadata</CardTitle></CardHeader>
            <CardContent className="grid gap-2 text-sm text-slate-600">
              <p><strong className="text-navy-900">Category:</strong> {document.category}</p>
              <p><strong className="text-navy-900">Visibility:</strong> {document.visibility}</p>
              <p><strong className="text-navy-900">MIME:</strong> {document.mimeType}</p>
              <p><strong className="text-navy-900">Uploaded:</strong> {format(document.createdAt, "MMM d, yyyy h:mm a")}</p>
              {document.description ? <p><strong className="text-navy-900">Description:</strong> {document.description}</p> : null}
              <div><Button asChild variant="secondary" size="sm"><a href={`/api/admin/documents/${document.id}/download`}>Download</a></Button></div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Upload new version</CardTitle></CardHeader>
            <CardContent><AddVersionForm documentId={document.id} /></CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Archive</CardTitle></CardHeader>
            <CardContent>
              <ArchiveDocumentForm documentId={document.id} />
            </CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle>Version history</CardTitle></CardHeader>
        <CardContent>
          <ul className="grid gap-3">
            {versions.map((version) => (
              <li key={version.id} className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-control)] border border-slate-200 p-3">
                <div>
                  <p className="font-semibold text-navy-900">Version {version.version}</p>
                  <p className="text-xs text-slate-500">{version.filename} · {(version.sizeBytes / 1024).toFixed(0)} KB · {format(version.createdAt, "MMM d, yyyy h:mm a")}</p>
                </div>
                <RestoreVersionForm documentId={document.id} version={version.version} />
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
