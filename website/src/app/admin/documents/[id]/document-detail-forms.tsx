"use client";

import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  addVersionAction,
  archiveDocumentAction,
  restoreVersionAction,
} from "../actions";
import {
  initialDocumentActionState,
  type DocumentActionState,
} from "../action-state";

function Result({ state }: { state: DocumentActionState }) {
  if (state.status === "idle") return null;
  return <div className="mt-3"><Alert tone={state.status === "success" ? "success" : "error"}>{state.message}</Alert></div>;
}

export function AddVersionForm({ documentId }: { documentId: string }) {
  const [state, action, pending] = useActionState(addVersionAction, initialDocumentActionState);
  return (
    <form action={action} className="grid gap-3">
      <input type="hidden" name="documentId" value={documentId} />
      <div className="grid gap-2">
        <Label htmlFor="new-version-file">New version (10 MB maximum)</Label>
        <Input id="new-version-file" name="file" type="file" required />
      </div>
      <Button type="submit" variant="secondary" disabled={pending}>{pending ? "Uploading…" : "Upload new version"}</Button>
      <Result state={state} />
    </form>
  );
}

export function RestoreVersionForm({ documentId, version }: { documentId: string; version: number }) {
  const [state, action, pending] = useActionState(restoreVersionAction, initialDocumentActionState);
  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="documentId" value={documentId} />
      <input type="hidden" name="version" value={version} />
      <Button type="submit" variant="secondary" size="sm" disabled={pending}>{pending ? "Restoring…" : `Restore v${version}`}</Button>
      <Result state={state} />
    </form>
  );
}

export function ArchiveDocumentForm({ documentId }: { documentId: string }) {
  const [state, action, pending] = useActionState(archiveDocumentAction, initialDocumentActionState);
  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="documentId" value={documentId} />
      <Button type="submit" variant="danger" size="sm" disabled={pending}>{pending ? "Archiving…" : "Archive document"}</Button>
      <Result state={state} />
    </form>
  );
}
