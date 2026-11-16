"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { authClient } from "@/lib/auth/client";

export function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (password.length < 12) {
      setError("Use at least 12 characters for your password.");
      return;
    }
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setPending(true);
    try {
      const result = await authClient.resetPassword({
        newPassword: password,
        token,
      });
      if (result.error) {
        setError(result.error.message || "Unable to reset the password.");
        return;
      }
      setSuccess(true);
      setPassword("");
      setConfirmation("");
    } catch {
      setError("Unable to reset the password. Please request a new link.");
    } finally {
      setPending(false);
    }
  }

  if (!token) {
    return (
      <Alert tone="error">
        This reset link is missing its token. Request a new password reset link.
      </Alert>
    );
  }

  if (success) {
    return (
      <div className="grid gap-4">
        <Alert tone="success" role="status">
          Your password has been reset. Sign in with your new password.
        </Alert>
        <Button asChild>
          <Link href="/login">Go to sign in</Link>
        </Button>
      </div>
    );
  }

  return (
    <form className="grid gap-5" method="post" onSubmit={submit}>
      {error ? <Alert tone="error" role="alert">{error}</Alert> : null}
      <div className="grid gap-2">
        <Label htmlFor="password">New password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          minLength={12}
          maxLength={512}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="confirmation">Confirm password</Label>
        <Input
          id="confirmation"
          type="password"
          autoComplete="new-password"
          minLength={12}
          maxLength={512}
          value={confirmation}
          onChange={(event) => setConfirmation(event.target.value)}
          required
        />
      </div>
      <Button type="submit" disabled={pending}>
        {pending ? "Resettingâ€¦" : "Reset password"}
      </Button>
    </form>
  );
}
