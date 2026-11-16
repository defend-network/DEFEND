"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FieldError, Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";

type Status = "loading" | "valid" | "success" | "expired" | "consumed" | "revoked" | "invalid" | "error";

type StatusResponse = {
  state?: string;
  email?: string;
  expiresAt?: string;
  error?: string;
};

const unavailable: Record<
  Exclude<Status, "loading" | "valid" | "success" | "error">,
  string
> = {
  expired:
    "This invitation has expired. Ask an administrator to send a new invitation.",
  consumed:
    "This invitation has already been used. Sign in with your account instead.",
  revoked:
    "This invitation has been revoked. Contact DEFEND if you need access.",
  invalid: "This invitation is invalid or unavailable.",
};

export function ActivationForm() {
  const tokenRef = useRef("");
  const capturedRef = useRef(false);
  const [status, setStatus] = useState<Status>("loading");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!capturedRef.current) {
      const fragment = new URLSearchParams(window.location.hash.slice(1));
      tokenRef.current = fragment.get("token") ?? "";
      capturedRef.current = true;
      window.history.replaceState(
        window.history.state,
        "",
        `${window.location.pathname}${window.location.search}`,
      );
    }

    if (!tokenRef.current) {
      setStatus("invalid");
      return;
    }

    let active = true;
    fetch("/api/invitations/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: tokenRef.current }),
    })
      .then(async (response) => {
        const data = (await response.json()) as StatusResponse;
        if (!active) return;
        if (data.state === "pending") {
          setEmail(data.email ?? "");
          setStatus("valid");
          return;
        }
        if (
          data.state === "expired" ||
          data.state === "consumed" ||
          data.state === "revoked" ||
          data.state === "invalid"
        ) {
          tokenRef.current = "";
          setStatus(data.state);
          return;
        }
        setStatus("error");
      })
      .catch(() => {
        if (active) setStatus("error");
      });

    return () => {
      active = false;
    };
  }, []);

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
      const response = await fetch("/api/invitations/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: tokenRef.current,
          name: name.trim(),
          password,
        }),
      });
      const data = (await response.json()) as { error?: string; email?: string };
      if (!response.ok) {
        setPassword("");
        setConfirmation("");
        setError(data.error || "We could not activate this account.");
        return;
      }
      tokenRef.current = "";
      setPassword("");
      setConfirmation("");
      setStatus("success");
    } catch {
      setError("We could not activate this account. Please try again.");
    } finally {
      setPending(false);
    }
  }

  if (status === "loading") {
    return <p className="text-sm text-slate-500">Checking your invitationâ€¦</p>;
  }

  if (status === "success") {
    return (
      <div className="grid gap-5">
        <Alert tone="success" role="status">
          Your account is active. You can now sign in.
        </Alert>
        <Button asChild size="lg">
          <Link href="/login">Go to sign in</Link>
        </Button>
      </div>
    );
  }

  if (status === "valid") {
    return (
      <form className="grid gap-5" method="post" onSubmit={submit}>
        {error ? (
          <Alert tone="error" role="alert">
            {error}
          </Alert>
        ) : null}
        <p className="text-sm leading-6 text-slate-600">
          {email ? `Activate the account for ${email}.` : "Activate your account."}
        </p>

        <div className="grid gap-2">
          <Label htmlFor="name">Your name</Label>
          <Input
            id="name"
            name="name"
            autoComplete="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            autoFocus
          />
        </div>

        <div className="grid gap-2">
          <Label htmlFor="password">New password</Label>
          <Input
            id="password"
            name="password"
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
            name="confirmation"
            type="password"
            autoComplete="new-password"
            minLength={12}
            maxLength={512}
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            required
          />
          <FieldError>{error}</FieldError>
        </div>

        <Button type="submit" size="lg" disabled={pending}>
          {pending ? "Activatingâ€¦" : "Activate account"}
        </Button>
      </form>
    );
  }

  if (status === "error") {
    return (
      <Alert tone="error">
        We could not verify this invitation. Please try again or contact DEFEND.
      </Alert>
    );
  }

  return (
    <div className="grid gap-5">
      <Alert tone="error">{unavailable[status]}</Alert>
      <Button asChild variant="secondary">
        <Link href="/contact">Contact DEFEND</Link>
      </Button>
    </div>
  );
}
