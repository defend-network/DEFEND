"use client";

import { useEffect, useState } from "react";

import { ApiError } from "@/app/workspace/load-workspace";

export type OwnerRuntimeStatus = {
  state: string | null;
  model: string | null;
  provider: string | null;
  instance_id: string | number | null;
  gpu: string | null;
  hourly_cost: string | null;
  endpoint: string | null;
  runtime_ready: boolean;
  routing_available: boolean;
  model_selectable: boolean;
  runtime_resumable: boolean;
};

export default function RuntimePanel({
  role,
  csrfToken,
}: {
  role: string;
  csrfToken: string | null;
}) {
  const [status, setStatus] = useState<OwnerRuntimeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setError(null);
    try {
      const response = await fetch("/v1/admin/runtime", {
        credentials: "include",
        headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
      });
      if (!response.ok) {
        setStatus(null);
        return;
      }
      setStatus((await response.json()) as OwnerRuntimeStatus);
    } catch {
      setStatus(null);
    }
  }

  useEffect(() => {
    if (role === "admin") {
      void load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  if (role !== "admin") {
    return null;
  }

  async function act(path: string, body?: Record<string, unknown>) {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(path, {
        method: "POST",
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
          ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) {
        const data = (await response.json().catch(() => null)) as {
          detail?: string;
        } | null;
        setError(data?.detail ?? `request failed (${response.status})`);
        return;
      }
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "action failed");
    } finally {
      setBusy(false);
    }
  }

  const state = status?.state ?? "UNKNOWN";

  return (
    <section className="runtime-panel" aria-label="Runtime">
      <h3 className="runtime-panel-title">Runtime</h3>
      {error && <p className="muted">{error}</p>}
      <dl className="runtime-facts">
        <dt>State</dt>
        <dd>{state}</dd>
        <dt>Model</dt>
        <dd>{status?.model ?? "—"}</dd>
        <dt>Provider</dt>
        <dd>{status?.provider ?? "—"}</dd>
        <dt>Instance</dt>
        <dd>{status?.instance_id ?? "—"}</dd>
        <dt>GPU</dt>
        <dd>{status?.gpu ?? "—"}</dd>
        <dt>$/hr</dt>
        <dd>{status?.hourly_cost ?? "—"}</dd>
        <dt>Health</dt>
        <dd>{status?.runtime_ready ? "READY" : "not ready"}</dd>
      </dl>
      <div className="runtime-actions">
        {status?.runtime_ready && (
          <button type="button" disabled={busy} onClick={() => void act("/v1/admin/runtime/stop-retain")}>
            Stop &amp; Retain
          </button>
        )}
        {status?.runtime_resumable && (
          <button type="button" disabled={busy} onClick={() => void act("/v1/admin/runtime/resume")}>
            Resume Retained
          </button>
        )}
        {status?.runtime_resumable && status.instance_id != null && (
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              const confirmed = window.prompt(
                `Type the exact instance ID to destroy: ${status.instance_id}`
              );
              if (confirmed === String(status.instance_id)) {
                void act("/v1/admin/runtime/destroy", {
                  instance_id: status.instance_id,
                });
              }
            }}
          >
            Destroy Exact
          </button>
        )}
        {state === "ABSENT" && (
          <button type="button" disabled={busy} onClick={() => void act("/v1/admin/runtime/plan")}>
            Plan Runtime
          </button>
        )}
      </div>
    </section>
  );
}
