"use client";

import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type CheckinResult = {
  ok: boolean;
  error?: string;
  alreadyCheckedIn?: boolean;
  memberName?: string;
  memberNumber?: string;
  chapterName?: string;
  status?: string;
  eventTitle?: string;
  checkedInAt?: string;
};

export function CheckinForm({
  events,
}: {
  events: Array<{ id: string; title: string }>;
}) {
  const [token, setToken] = useState("");
  const [eventId, setEventId] = useState(events[0]?.id ?? "");
  const [result, setResult] = useState<CheckinResult | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setResult(null);
    try {
      const response = await fetch("/api/admin/checkin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token.trim(), eventId: eventId || undefined }),
      });
      const json = (await response.json()) as CheckinResult;
      setResult(json);
      if (json.ok) setToken("");
    } catch {
      setResult({ ok: false, error: "Check-in request failed." });
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="grid gap-5">
      <form onSubmit={submit} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 bg-white p-5">
        <div className="grid gap-2">
          <Label htmlFor="eventId">Event (optional for card verification)</Label>
          <select
            id="eventId"
            value={eventId}
            onChange={(event) => setEventId(event.target.value)}
            className="h-11 rounded-[var(--radius-control)] border border-slate-300 bg-white px-3 text-sm"
          >
            <option value="">General card verification</option>
            {events.map((event) => (
              <option key={event.id} value={event.id}>
                {event.title}
              </option>
            ))}
          </select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor="token">Card code</Label>
          <Input
            id="token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder="Paste the scanned or short-lived card token"
            required
          />
        </div>
        <Button type="submit" disabled={pending || !token.trim()}>
          {pending ? "Verifying…" : "Verify and check in"}
        </Button>
      </form>

      {result ? (
        result.ok ? (
          <Alert tone="success" role="status">
            <strong>{result.memberName}</strong> · {result.memberNumber} ·{" "}
            {result.chapterName} · {result.status?.replaceAll("_", " ")}
            {result.eventTitle ? ` · ${result.eventTitle}` : ""}
            {result.alreadyCheckedIn ? " · already checked in" : " · checked in"}
          </Alert>
        ) : (
          <Alert tone="error" role="alert">
            {result.error || "Check-in failed."}
          </Alert>
        )
      ) : null}

      <Alert tone="info">
        The QR code contains a short-lived signed token, not a member ID or
        personal information. Camera scanning is not enabled in this build; use a
        compatible scanner that types the token into the field.
      </Alert>
    </div>
  );
}
