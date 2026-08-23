"use client";

import { useRef, useState } from "react";
import type { JobRecord } from "@/lib/reportTypes";
import { uploadPhotos } from "@/lib/reportsApi";

export function PhotosForm({
  record,
  commit,
  onNext,
  onBack,
}: {
  record: JobRecord;
  commit: (record: JobRecord) => void;
  onNext: () => void;
  onBack: () => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [progress, setProgress] = useState<{ uploaded: number; total: number } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(files: FileList | null) {
    if (!files || files.length === 0) {
      return;
    }
    setError(null);
    setUploading(true);
    try {
      const payload = await uploadPhotos(record.metadata.job_id, Array.from(files), (uploaded, total) =>
        setProgress({ uploaded, total }),
      );
      const existing = new Set(record.photos.map((photo) => photo.sha256));
      const fresh = payload.photos.filter((photo) => !existing.has(photo.sha256));
      commit({ ...record, photos: [...record.photos, ...fresh] });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Upload failed");
    } finally {
      setUploading(false);
      setProgress(null);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
    }
  }

  function removePhoto(photoId: string) {
    commit({
      ...record,
      photos: record.photos.filter((photo) => photo.photo_id !== photoId),
    });
  }

  return (
    <div>
      <h4>Photos & evidence</h4>
      <p className="muted">
        Originals are preserved byte-for-byte with a SHA-256 manifest. No image understanding is
        configured — every value in the report stays technician-entered.
      </p>
      <label className="reports-dropzone">
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="image/*,.heic,.txt"
          onChange={(e) => void upload(e.target.files)}
          disabled={uploading}
        />
        <span>
          {uploading
            ? progress
              ? `Uploading… ${Math.round((progress.uploaded / progress.total) * 100)}%`
              : "Uploading…"
            : "Choose photos (multiple) — or drop them here"}
        </span>
      </label>
      {error && (
        <p role="alert" className="login-error">
          {error}
        </p>
      )}
      <div className="reports-photo-count">
        <span className="pill">{record.photos.length} photo{record.photos.length === 1 ? "" : "s"} in manifest</span>
      </div>
      <div className="reports-photo-grid">
        {record.photos.map((photo) => (
          <article className="reports-photo-card" key={photo.photo_id}>
            <div className="reports-photo-thumb" aria-hidden="true">
              {photo.original_filename.split(".").pop()?.toUpperCase() ?? "?"}
            </div>
            <div className="reports-photo-meta">
              <span className="pill pill-field">{photo.photo_id}</span>
              <p title={photo.original_filename}>{photo.original_filename}</p>
              <p className="muted">
                {photo.review_status.replace(/_/g, " ").toLowerCase()} · sha256{" "}
                {photo.sha256.slice(0, 8)}…
              </p>
              <button className="button-link danger" onClick={() => removePhoto(photo.photo_id)}>
                Remove
              </button>
            </div>
          </article>
        ))}
      </div>
      {record.photos.length === 0 && <div className="empty">No photos attached yet.</div>}
      <div className="reports-actions">
        <button className="button-secondary" onClick={onBack}>
          ← Readings
        </button>
        <button className="button-primary" onClick={onNext}>
          Next: Review →
        </button>
      </div>
    </div>
  );
}