"use client";

import { useEffect, useState } from "react";

export type FileViewerState =
  | { kind: "loading" }
  | { kind: "binary"; size: number }
  | { kind: "error"; message: string }
  | { kind: "content"; content: string; size: number };

const MAX_DISPLAY_BYTES = 256 * 1024;

function renderLines(content: string) {
  const lines = content.split("\n");
  const shown = lines.slice(0, 5000);
  const truncated = lines.length > shown.length;
  return { lines: shown, truncated };
}

export default function FileViewer({
  path,
  load,
  onClose,
}: {
  path: string;
  load: () => Promise<{ binary: boolean; content: string | null; size: number }>;
  onClose: () => void;
}) {
  const [state, setState] = useState<FileViewerState>({ kind: "loading" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    setError(null);
    load()
      .then((result) => {
        if (cancelled) return;
        if (result.binary || result.content === null) {
          setState({ kind: "binary", size: result.size });
        } else if (result.size > MAX_DISPLAY_BYTES) {
          setError(
            `File is ${result.size} bytes; only the first ${MAX_DISPLAY_BYTES} bytes are shown for large files.`
          );
          setState({ kind: "content", content: result.content, size: result.size });
        } else {
          setState({ kind: "content", content: result.content, size: result.size });
        }
      })
      .catch(() => {
        if (cancelled) return;
        setState({ kind: "error", message: "Unable to read file." });
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  return (
    <div className="file-viewer" role="dialog" aria-label={`Viewing ${path}`}>
      <header className="file-viewer-header">
        <span className="file-viewer-path" title={path}>
          {path}
        </span>
        <button type="button" onClick={onClose} aria-label="Close file viewer">
          Close
        </button>
      </header>
      <div className="file-viewer-body">
        {state.kind === "loading" && <p className="muted">Loading…</p>}
        {state.kind === "binary" && (
          <p className="muted">Binary file ({state.size} bytes) — not displayed.</p>
        )}
        {state.kind === "error" && <p className="muted">{state.message}</p>}
        {state.kind === "content" && (
          <>
            {error && <p className="muted">{error}</p>}
            <pre className="file-viewer-code">
              <code>
                {renderLines(state.content).lines.map((line, index) => (
                  <span className="file-viewer-line" key={index}>
                    <span className="file-viewer-lineno">{index + 1}</span>
                    {line || " "}
                    {"\n"}
                  </span>
                ))}
              </code>
            </pre>
            {renderLines(state.content).truncated && (
              <p className="muted">… further lines omitted (file truncated for display).</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
