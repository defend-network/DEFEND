"use client";

import QRCodeSVG from "react-qr-code";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authClient } from "@/lib/auth/client";

export function MfaSettings({ enabled }: { enabled: boolean }) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [totpURI, setTotpURI] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);

  async function enable(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setPending(true);
    try {
      const result = await authClient.twoFactor.enable({ password });
      if (result.error) {
        setError(result.error.message || "Unable to start MFA enrollment.");
        return;
      }
      const data = result.data as
        | { totpURI?: string; backupCodes?: string[] }
        | undefined;
      if (!data?.totpURI) {
        setError("The authentication service did not return a TOTP enrollment URI.");
        return;
      }
      setTotpURI(data.totpURI);
      setBackupCodes(data.backupCodes ?? []);
      setPassword("");
      setMessage(
        "Scan the QR code with an authenticator app, then enter the six-digit code to finish enrollment.",
      );
    } finally {
      setPending(false);
    }
  }

  async function verify(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setPending(true);
    try {
      const result = await authClient.twoFactor.verifyTotp({ code });
      if (result.error) {
        setError(result.error.message || "Invalid authentication code.");
        return;
      }
      setCode("");
      setMessage(
        "Multi-factor authentication is enabled. Store the backup codes in a safe place.",
      );
      router.refresh();
    } finally {
      setPending(false);
    }
  }

  async function disable(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setPending(true);
    try {
      const result = await authClient.twoFactor.disable({ password });
      if (result.error) {
        setError(result.error.message || "Unable to disable MFA.");
        return;
      }
      setPassword("");
      setMessage("Multi-factor authentication is disabled.");
      router.refresh();
    } finally {
      setPending(false);
    }
  }

  if (enabled) {
    return (
      <div className="grid gap-5">
        <Alert tone="success">
          Multi-factor authentication is enabled for this account. Sign-in
          requires an authenticator code or a backup code.
        </Alert>
        <form onSubmit={disable} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 p-5">
          <div>
            <h3 className="text-lg font-semibold">Disable MFA</h3>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Disabling MFA reduces account security and will be recorded in the
              audit log. Administrative mutations will fail closed until MFA is
              re-enabled.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="disable-password">Password</Label>
            <Input
              id="disable-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
          {error ? <Alert tone="error">{error}</Alert> : null}
          {message ? <Alert tone="success">{message}</Alert> : null}
          <Button type="submit" variant="danger" disabled={pending}>
            {pending ? "Disabling…" : "Disable MFA"}
          </Button>
        </form>
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <Alert tone="info">
        Enroll an authenticator app before performing administrative review or
        member-management actions. TOTP codes are six digits and rotate every 30
        seconds.
      </Alert>

      {!totpURI ? (
        <form onSubmit={enable} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 p-5">
          <div className="grid gap-2">
            <Label htmlFor="enable-password">Confirm your password</Label>
            <Input
              id="enable-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
          {error ? <Alert tone="error">{error}</Alert> : null}
          {message ? <Alert tone="info">{message}</Alert> : null}
          <Button type="submit" disabled={pending}>
            {pending ? "Starting…" : "Start MFA enrollment"}
          </Button>
        </form>
      ) : (
        <div className="grid gap-5 rounded-[var(--radius-card)] border border-slate-200 p-5">
          <div className="flex flex-wrap items-start gap-6">
            <div className="rounded-[var(--radius-control)] bg-white p-3 shadow-sm">
              <QRCodeSVG value={totpURI} size={180} />
            </div>
            <div className="max-w-md">
              <h3 className="text-lg font-semibold">Scan and verify</h3>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                Open your authenticator app, scan this code, and enter the
                current six-digit code below. Do not share this QR code.
              </p>
            </div>
          </div>
          <form onSubmit={verify} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="totp-code">Authentication code</Label>
              <Input
                id="totp-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]{6}"
                maxLength={6}
                value={code}
                onChange={(event) =>
                  setCode(event.target.value.replace(/\D/g, ""))
                }
                required
              />
            </div>
            {error ? <Alert tone="error">{error}</Alert> : null}
            {message ? <Alert tone="info">{message}</Alert> : null}
            <Button type="submit" disabled={pending || code.length !== 6}>
              {pending ? "Verifying…" : "Verify and enable MFA"}
            </Button>
          </form>
          {backupCodes.length ? (
            <div className="rounded-[var(--radius-control)] border border-warning-700/25 bg-warning-100 p-4">
              <p className="text-sm font-semibold text-warning-700">
                Backup codes — store these now
              </p>
              <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-warning-700">
                {backupCodes.join("\n")}
              </pre>
              <p className="mt-2 text-xs leading-5 text-warning-700">
                These codes are shown once. Each code can be used once if you
                lose access to your authenticator.
              </p>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
