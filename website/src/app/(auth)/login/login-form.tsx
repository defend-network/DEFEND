"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FieldError, Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { authClient } from "@/lib/auth/client";

function safeNext(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/members";
  }
  return value;
}

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPending(true);

    try {
      const result = await authClient.signIn.email({
        email: email.trim(),
        password,
      });

      if (result.error) {
        setError(
          result.error.message ||
            "Unable to sign in. Check your email and password.",
        );
        setPassword("");
        return;
      }

      const data = result.data as
        | { twoFactorRedirect?: boolean }
        | null
        | undefined;
      if (data?.twoFactorRedirect) {
        router.push(
          `/login/two-factor?next=${encodeURIComponent(
            safeNext(searchParams.get("next")),
          )}`,
        );
        return;
      }

      router.push(safeNext(searchParams.get("next")));
      router.refresh();
    } catch {
      setError("Unable to sign in. Please try again.");
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
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          autoFocus
        />
      </div>

      <div className="grid gap-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="password">Password</Label>
          <Link
            href="/forgot-password"
            className="text-xs font-semibold text-slate-500 underline-offset-4 hover:text-navy-900 hover:underline"
          >
            Forgot password?
          </Link>
        </div>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        <FieldError />
      </div>

      <Button type="submit" size="lg" disabled={pending}>
        {pending ? "Signing in…" : "Sign in"}
      </Button>

      <div className="text-center">
        <Link
          href="/login/email-code"
          className="text-sm font-semibold text-red-700 underline-offset-4 hover:underline"
        >
          Email me a sign-in code
        </Link>
      </div>

      <p className="text-xs leading-5 text-slate-500">
        Paid member accounts are invitation-based after approval. Free accounts
        can be created from the membership page.
      </p>
    </form>
  );
}
