"use client";

import { useState } from "react";
import {
  adminRagIngest,
  adminRagJob,
  PermanentRagDocument,
  RagJob,
} from "@/lib/api";

type Props = {
  token: string;
  documents: PermanentRagDocument[];
  onDocumentsChanged: () => void | Promise<void>;
  pollIntervalMs?: number;
};

const allowed = (file: File) => /\.(pdf|docx)$/i.test(file.name);

export function KnowledgeRagPanel({
  token,
  documents,
  onDocumentsChanged,
  pollIntervalMs = 2000,
}: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [job, setJob] = useState<RagJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function choose(input: FileList | null) {
    const selected = Array.from(input ?? []);
    setJob(null);
    if (selected.length > 20) {
      setFiles([]);
      setError("Choose at most 20 PDF or DOCX files per batch.");
      return;
    }
    const unsupported = selected.find((file) => !allowed(file));
    if (unsupported) {
      setFiles([]);
      setError(`${unsupported.name} is not a PDF or DOCX file.`);
      return;
    }
    setError("");
    setFiles(selected);
  }

  async function start() {
    if (!files.length || busy) return;
    setBusy(true);
    setError("");
    try {
      let current = await adminRagIngest(token, files);
      setJob(current);
      while (current.status !== "complete" && current.status !== "failed") {
        await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
        current = await adminRagJob(token, current.job_id);
        setJob(current);
      }
      await onDocumentsChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  const finished = (job?.indexed ?? 0) + (job?.skipped ?? 0) + (job?.failed ?? 0);
  const progress = job?.total ? Math.round((finished / job.total) * 100) : 0;

  return (
    <>
      <div className="page-heading">
        <span className="eyebrow">Corpus</span>
        <h1>Knowledge / RAG</h1>
        <p>Permanently index operator-approved PDF and DOCX documents.</p>
      </div>

      <section className="admin-card rag-ingest-card" aria-labelledby="rag-ingest-heading">
        <h2 id="rag-ingest-heading">Add permanent documents</h2>
        <p className="muted">Up to 20 files per batch and 25 MB per file. Identical content is skipped.</p>
        <label className="rag-file-label">
          Choose PDF or DOCX files
          <input
            type="file"
            multiple
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            disabled={busy}
            onChange={(event) => choose(event.target.files)}
          />
        </label>
        {files.length > 0 && (
          <ul className="rag-selected-files">
            {files.map((file) => <li key={`${file.name}-${file.size}`}>{file.name} · {(file.size / 1024).toFixed(1)} KB</li>)}
          </ul>
        )}
        <button type="button" onClick={start} disabled={!files.length || busy}>
          {busy ? "Indexing…" : `Index ${files.length} document${files.length === 1 ? "" : "s"}`}
        </button>
        {error && <p className="admin-error" role="alert">{error}</p>}

        {job && (
          <div className="rag-job" aria-live="polite">
            <progress value={finished} max={job.total || 1} aria-label="Permanent RAG ingestion progress" />
            <p>{progress}% · <strong>{job.indexed} indexed</strong> · <strong>{job.skipped} skipped</strong> · <strong>{job.failed} failed</strong></p>
            <div className="rag-job-files">
              {job.files.map((item) => (
                <div className={`rag-job-file rag-job-file--${item.status}`} key={item.document_id}>
                  <strong>{item.name}</strong><span>{item.status}</span>
                  {item.error && <p>{item.error}</p>}
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="admin-card rag-corpus" aria-labelledby="rag-corpus-heading">
        <h2 id="rag-corpus-heading">Permanent corpus</h2>
        {documents.length ? (
          <div className="rag-document-list">
            {documents.map((document) => (
              <article key={document.document_id} className="doc-row">
                <div>
                  <strong>{document.title}</strong>
                  <span>{document.chunk_count} chunks · {document.embedding_model}</span>
                  <span>{document.document_id}</span>
                </div>
              </article>
            ))}
          </div>
        ) : <p className="muted">No permanent documents indexed yet.</p>}
      </section>
    </>
  );
}
