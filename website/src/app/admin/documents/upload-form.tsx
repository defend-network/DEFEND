"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { uploadDocumentAction } from "./actions";
import {
  initialDocumentActionState,
  type DocumentActionState,
} from "./action-state";

export function DocumentUploadForm() {
  const [state, action, pending] = useActionState(
    uploadDocumentAction,
    initialDocumentActionState,
  ) as [DocumentActionState, (formData: FormData) => void, boolean];

  return (
    <form action={action} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">Upload document</h2>
      <div className="grid gap-2">
        <Label htmlFor="doc-file">File (10 MB maximum)</Label>
        <Input id="doc-file" name="file" type="file" required />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="doc-title">Title</Label>
        <Input id="doc-title" name="title" />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="doc-description">Description</Label>
        <Textarea id="doc-description" name="description" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="doc-category">Category</Label>
          <select id="doc-category" name="category" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="governance">Governance</option>
            <option value="finance">Finance</option>
            <option value="chapter">Chapter</option>
            <option value="program">Program</option>
            <option value="legal">Legal</option>
            <option value="general">General</option>
          </select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="doc-visibility">Visibility</Label>
          <select id="doc-visibility" name="visibility" className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm">
            <option value="admin">Admin only</option>
            <option value="chapter">Chapter</option>
            <option value="members">Members</option>
            <option value="public">Public</option>
          </select>
        </div>
      </div>
      {state.status === "success" ? <Alert tone="success">{state.message}</Alert> : null}
      {state.status === "error" ? <Alert tone="error">{state.message}</Alert> : null}
      <Button type="submit" disabled={pending}>
        {pending ? "Uploading…" : "Upload document"}
      </Button>
      <p className="text-xs leading-5 text-slate-500">
        Files are stored in private R2 storage. Downloads are authorized and
        audited server-side.
      </p>
    </form>
  );
}
