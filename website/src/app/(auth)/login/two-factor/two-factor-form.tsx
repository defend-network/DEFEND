"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
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
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);
    try {
      const result = await authClient.twoFactor.verifyTotp({ code });
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

  return (
    <form className="grid gap-5" method="post" onSubmit={submit}>
      {error ? (
        <Alert tone="error" role="alert">
          {error}
        </Alert>
      ) : null}
      <div className="grid gap-2">
        <Label htmlFor="code">Authentication code</Label>
        <Input
          id="code"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
          required
          autoFocus
        />
      </div>
      <Button type="submit" size="lg" disabled={pending || code.length !== 6}>
        {pending ? "Verifyingâ€¦" : "Verify and continue"}
      </Button>
    </form>
  );
}
