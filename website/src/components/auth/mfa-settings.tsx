"use client";

import QRCodeSVG from "react-qr-code";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authClient } from "@/lib/auth/client";

function downloadCodes(codes: string[]) {
  const blob = new Blob([`DEFEND recovery codes\n\n${codes.join("\n")}\n`], {
    type: "text/plain",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "defend-recovery-codes.txt";
  anchor.click();
  URL.revokeObjectURL(url);
}

function RecoveryCodesOnce({
  codes,
  onDone,
}: {
  codes: string[];
  onDone: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(codes.join("\n"));
    setCopied(true);
  }

  return (
    <div className="rounded-[var(--radius-control)] border border-warning-700/25 bg-warning-100 p-4">
      <p className="text-sm font-semibold text-warning-700">
        Recovery codes — save these now
      </p>
      <p className="mt-1 text-xs leading-5 text-warning-700">
        These codes are shown once. Each code is single-use. Do not share them.
      </p>
      <pre className="mt-3 whitespace-pre-wrap font-mono text-xs text-warning-700">
        {codes.join("\n")}
      </pre>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="secondary" onClick={() => downloadCodes(codes)}>
          Download codes
        </Button>
        <Button type="button" size="sm" variant="secondary" onClick={copy}>
          {copied ? "Copied" : "Copy codes"}
        </Button>
        <Button type="button" size="sm" onClick={onDone}>
          I have saved these codes
        </Button>
      </div>
    </div>
  );
}

export function MfaSettings({ enabled }: { enabled: boolean }) {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [totpURI, setTotpURI] = useState("");
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [verified, setVerified] = useState(false);
  const [generatedCodes, setGeneratedCodes] = useState<string[]>([]);

  async function enable(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setPending(true);
    try {
      const result = await authClient.twoFactor.enable({ password });
      if (result.error) {
        setError(result.error.message || "Unable to start authenticator setup.");
        return;
      }
      const data = result.data as
        | { totpURI?: string; backupCodes?: string[] }
        | undefined;
      if (!data?.totpURI) {
        setError("The authentication service did not return an enrollment URI.");
        return;
      }
      setTotpURI(data.totpURI);
      setBackupCodes(data.backupCodes ?? []);
      setPassword("");
      setVerified(false);
      setMessage(
        "Scan the QR code and enter the current six-digit code to finish enrollment. Recovery codes will be shown only after verification.",
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
      setVerified(true);
      setMessage(
        "Authenticator app enabled. Save the recovery codes below before leaving this page.",
      );
    } finally {
      setPending(false);
    }
  }

  async function finishEnrollment() {
    setBackupCodes([]);
    setVerified(false);
    setTotpURI("");
    setMessage("");
    router.refresh();
  }

  async function generateCodes(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setPending(true);
    try {
      const result = await authClient.twoFactor.generateBackupCodes({ password });
      if (result.error) {
        setError(result.error.message || "Unable to generate new recovery codes.");
        return;
      }
      const data = result.data as { backupCodes?: string[] } | undefined;
      setGeneratedCodes(data?.backupCodes ?? []);
      setPassword("");
      setMessage("New recovery codes generated. Previous recovery codes are invalid.");
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
        setError(result.error.message || "Unable to disable the authenticator app.");
        return;
      }
      setPassword("");
      setMessage("Authenticator app disabled.");
      router.refresh();
    } finally {
      setPending(false);
    }
  }

  if (enabled) {
    return (
      <div className="grid gap-5">
        <Alert tone="success">
          Authenticator app is enabled. Sign-in can use a current authenticator
          code or a single-use recovery code.
        </Alert>

        <form onSubmit={generateCodes} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 p-5">
          <div>
            <h3 className="text-lg font-semibold">Generate new recovery codes</h3>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Generating new codes invalidates all previous recovery codes. The
              new codes are shown once.
            </p>
          </div>
          <div className="grid gap-2">
            <Label htmlFor="generate-codes-password">Password</Label>
            <Input
              id="generate-codes-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </div>
          {error ? <Alert tone="error">{error}</Alert> : null}
          {message ? <Alert tone="info">{message}</Alert> : null}
          <Button type="submit" variant="secondary" disabled={pending}>
            {pending ? "Generating…" : "Generate new recovery codes"}
          </Button>
        </form>

        {generatedCodes.length ? (
          <RecoveryCodesOnce
            codes={generatedCodes}
            onDone={() => {
              setGeneratedCodes([]);
              setMessage("");
            }}
          />
        ) : null}

        <form onSubmit={disable} className="grid gap-4 rounded-[var(--radius-card)] border border-slate-200 p-5">
          <div>
            <h3 className="text-lg font-semibold">Disable authenticator app</h3>
            <p className="mt-1 text-sm leading-6 text-slate-600">
              Disabling the authenticator app reduces account security and is
              recorded in the audit log. Sensitive administrative actions will
              fail closed until a strong method is enabled again.
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
          <Button type="submit" variant="danger" disabled={pending}>
            {pending ? "Disabling…" : "Disable authenticator app"}
          </Button>
        </form>
      </div>
    );
  }

  if (verified) {
    return (
      <div className="grid gap-5">
        <Alert tone="success">
          Authenticator app enabled. Save the recovery codes now; they will not
          be shown again.
        </Alert>
        {backupCodes.length ? (
          <RecoveryCodesOnce codes={backupCodes} onDone={finishEnrollment} />
        ) : null}
      </div>
    );
  }

  return (
    <div className="grid gap-5">
      <Alert tone="info">
        Email is the default verification method. An authenticator app is
        optional but recommended for administrators and for sensitive actions.
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
            {pending ? "Starting…" : "Set up authenticator app"}
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
                current six-digit code. Do not share this QR code.
              </p>
              <p className="mt-2 text-xs leading-5 text-warning-700">
                Recovery codes are not active until verification succeeds. They
                are shown once after verification.
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
              {pending ? "Verifying…" : "Verify and enable authenticator"}
            </Button>
          </form>
        </div>
      )}
    </div>
  );
}
