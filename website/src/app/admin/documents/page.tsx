import type { Metadata } from "next";
import Link from "next/link";
import { format } from "date-fns";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { listDocuments } from "@/lib/documents/documents";
import { DocumentUploadForm } from "./upload-form";

export const metadata: Metadata = {
  title: "Documents",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default async function DocumentsPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; category?: string }>;
}) {
  const params = await searchParams;
  const query = params.q?.slice(0, 120) ?? "";
  const category = params.category ?? "all";
  const docs = await listDocuments({ query, category });

  return (
    <div className="grid gap-6">
      <div>
        <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
          Secure records
        </p>
        <h1 className="mt-3 text-3xl font-semibold">Documents</h1>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          Private R2 documents with categorized storage, authorized downloads, and
          audit history.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[0.75fr_1.25fr]">
        <DocumentUploadForm />
        <div className="grid gap-5">
          <Card>
            <CardContent className="p-5">
              <form action="/admin/documents" className="flex flex-col gap-3 sm:flex-row">
                <input
                  name="q"
                  defaultValue={query}
                  placeholder="Search title or filename"
                  className="h-11 flex-1 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm outline-none focus:border-navy-700 focus:ring-2 focus:ring-navy-800/15"
                />
                <select name="category" aria-label="Filter by category" defaultValue={category} className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
                  <option value="all">All categories</option>
                  <option value="governance">Governance</option>
                  <option value="finance">Finance</option>
                  <option value="chapter">Chapter</option>
                  <option value="program">Program</option>
                  <option value="legal">Legal</option>
                  <option value="general">General</option>
                </select>
                <Button type="submit" variant="secondary">Filter</Button>
              </form>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Library</CardTitle></CardHeader>
            <CardContent>
              {docs.length === 0 ? <p className="text-sm text-slate-500">No documents match.</p> : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[800px] text-left text-sm">
                    <thead className="border-b border-slate-200 text-xs uppercase tracking-[0.12em] text-slate-500">
                      <tr><th className="px-3 py-3">Document</th><th className="px-3 py-3">Category</th><th className="px-3 py-3">Visibility</th><th className="px-3 py-3">Uploaded</th><th className="px-3 py-3" /></tr>
                    </thead>
                    <tbody>
                      {docs.map((doc) => (
                        <tr key={doc.id} className="border-b border-slate-100 last:border-0">
                          <td className="px-3 py-3"><p className="font-semibold text-navy-900"><Link href={`/admin/documents/${doc.id}`} className="underline-offset-4 hover:underline">{doc.title}</Link></p><p className="text-xs text-slate-500">{doc.filename} · {(doc.sizeBytes / 1024).toFixed(0)} KB</p></td>
                          <td className="px-3 py-3 text-slate-600">{doc.category}</td>
                          <td className="px-3 py-3"><Badge variant="outline">{doc.visibility}</Badge></td>
                          <td className="px-3 py-3 text-slate-600">{format(doc.createdAt, "MMM d, yyyy")}</td>
                          <td className="px-3 py-3 text-right"><a href={`/api/admin/documents/${doc.id}/download`} className="text-sm font-semibold text-red-700 underline-offset-4 hover:underline">Download</a></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
