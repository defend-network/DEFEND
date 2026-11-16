"use client";

import QRCodeSVG from "react-qr-code";
import { useCallback, useEffect, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type CardData = {
  token: string;
  expiresAt: string;
  memberNumber: string;
  displayName: string;
  chapterName: string;
  status: string;
  duesStatus: string;
};

export function CardQr({ initialName }: { initialName: string }) {
  const [data, setData] = useState<CardData | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const response = await fetch("/api/members/card-token", {
        cache: "no-store",
      });
      const json = (await response.json()) as CardData & { error?: string };
      if (!response.ok) {
        setError(json.error || "Unable to load the membership card.");
        return;
      }
      setError("");
      setData(json);
    } catch {
      setError("Unable to load the membership card.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- token fetch is an external system read
    void load();
    const timer = window.setInterval(() => void load(), 4 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [load]);

  if (loading && !data) {
    return <p className="text-sm text-slate-500">Loading secure card…</p>;
  }
  if (error) {
    return <Alert tone="error">{error}</Alert>;
  }
  if (!data) return null;

  return (
    <div className="grid gap-5">
      <div className="overflow-hidden rounded-[var(--radius-panel)] bg-navy-900 text-white shadow-xl">
        <div className="h-1.5 bg-red-600" />
        <div className="grid gap-6 p-6 sm:grid-cols-[1fr_auto] sm:items-center">
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-red-400">
              DEFEND member
            </p>
            <p className="mt-2 font-serif text-2xl font-semibold">
              {data.displayName || initialName}
            </p>
            <p className="mt-1 font-mono text-sm text-slate-300">
              {data.memberNumber}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Badge variant="red" className="bg-red-600 text-white">
                {data.chapterName}
              </Badge>
              <Badge variant="outline" className="border-white/40 text-white">
                {data.status.replaceAll("_", " ")}
              </Badge>
              <Badge variant="outline" className="border-white/40 text-white">
                Dues: {data.duesStatus.replaceAll("_", " ")}
              </Badge>
            </div>
            <p className="mt-5 max-w-md text-xs leading-5 text-slate-400">
              This QR code expires and refreshes automatically. It contains no
              phone number, email address, or street address. Do not share it.
            </p>
          </div>
          <div className="rounded-[var(--radius-control)] bg-white p-3">
            <QRCodeSVG value={data.token} size={180} />
          </div>
        </div>
      </div>
      <div className="flex flex-wrap gap-3">
        <Button type="button" variant="secondary" onClick={() => void load()}>
          Refresh code
        </Button>
        <Button type="button" variant="secondary" onClick={() => window.print()}>
          Print card
        </Button>
        <span className="self-center text-xs text-slate-500">
          Code expires {new Date(data.expiresAt).toLocaleTimeString()}.
        </span>
      </div>
    </div>
  );
}
