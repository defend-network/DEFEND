"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authClient } from "@/lib/auth/client";

function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/members";
  }
  return value;
}

export function TwoFactorForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<"totp" | "backup">("totp");
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      const result =
        mode === "totp"
          ? await authClient.twoFactor.verifyTotp({ code })
          : await authClient.twoFactor.verifyBackupCode({ code });
      if (result.error) {
        setError(result.error.message || "Invalid authentication code.");
        return;
      }
      router.push(safeNext(searchParams.get("next")));
      router.refresh();
    } catch {
      setError("Unable to verify the code. Please try again.");
    } finally {
      setPending(false);
    }
  }

  const isTotp = mode === "totp";
  const canSubmit = isTotp ? code.length === 6 : code.trim().length >= 6;

  return (
    <form className="grid gap-5" method="post" onSubmit={submit}>
      {error ? (
        <Alert tone="error" role="alert">
          {error}
        </Alert>
      ) : null}
      <div className="grid gap-2">
        <Label htmlFor="code">
          {isTotp ? "Authenticator code" : "Backup code"}
        </Label>
        <Input
          id="code"
          name="code"
          inputMode={isTotp ? "numeric" : "text"}
          autoComplete="one-time-code"
          pattern={isTotp ? "[0-9]{6}" : undefined}
          maxLength={isTotp ? 6 : 40}
          value={code}
          onChange={(event) =>
            setCode(
              isTotp
                ? event.target.value.replace(/\D/g, "")
                : event.target.value.trim(),
            )
          }
          required
          autoFocus
        />
        <p className="text-xs leading-5 text-slate-500">
          {isTotp
            ? "Enter the current six-digit code from your authenticator app."
            : "Each backup code can be used once. It is invalidated after use."}
        </p>
      </div>
      <Button type="submit" size="lg" disabled={pending || !canSubmit}>
        {pending ? "Verifying…" : "Verify and continue"}
      </Button>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => {
          setMode(isTotp ? "backup" : "totp");
          setCode("");
          setError("");
        }}
      >
        {isTotp ? "Use a backup code instead" : "Use an authenticator code"}
      </Button>
    </form>
  );
}
