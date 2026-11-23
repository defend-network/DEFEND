"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

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

function maskEmail(value: string): string {
  const [local, domain] = value.split("@");
  if (!domain) return value;
  return `${local.slice(0, 1)}***@${domain}`;
}

export function EmailCodeForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"email" | "code">("email");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  async function sendCode(event?: React.FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    setError("");
    setMessage("");
    setPending(true);
    try {
      const normalized = email.trim().toLowerCase();
      const result = await authClient.emailOtp.sendVerificationOtp({
        email: normalized,
        type: "sign-in",
      });
      if (result.error) {
        setError(
          result.error.message ||
            "Unable to send a verification code. Check the address and try again.",
        );
        return;
      }
      setStep("code");
      setMessage(
        "If an account exists for that address, a six-digit code has been sent. It expires in 5 minutes.",
      );
      setCooldown(30);
    } catch {
      setError("Unable to send a verification code. Please try again.");
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
      const result = await authClient.signIn.emailOtp({
        email: email.trim().toLowerCase(),
        otp: code,
      });
      if (result.error) {
        setError(result.error.message || "Invalid or expired verification code.");
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
      setError("Unable to verify the code. Please try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form className="grid gap-5" onSubmit={step === "email" ? sendCode : verify}>
      {error ? (
        <Alert tone="error" role="alert">
          {error}
        </Alert>
      ) : null}
      {message ? <Alert tone="info">{message}</Alert> : null}

      <div className="grid gap-2">
        <Label htmlFor="email-code-email">Email address</Label>
        <Input
          id="email-code-email"
          name="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          disabled={step === "code"}
          autoFocus
        />
      </div>

      {step === "code" ? (
        <>
          <p className="text-sm text-slate-600">
            Code sent to <strong className="text-navy-900">{maskEmail(email.trim().toLowerCase())}</strong>
          </p>
          <div className="grid gap-2">
            <Label htmlFor="email-code">Six-digit code</Label>
            <Input
              id="email-code"
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
        </>
      ) : null}

      {step === "email" ? (
        <Button type="submit" size="lg" disabled={pending}>
          {pending ? "Sending…" : "Send sign-in code"}
        </Button>
      ) : (
        <div className="grid gap-3">
          <Button type="submit" size="lg" disabled={pending || code.length !== 6}>
            {pending ? "Verifying…" : "Verify and continue"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={pending || cooldown > 0}
            onClick={() => sendCode()}
          >
            {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              setStep("email");
              setCode("");
              setError("");
              setMessage("");
            }}
          >
            Use a different email
          </Button>
        </div>
      )}
    </form>
  );
}
