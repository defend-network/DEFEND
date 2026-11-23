"use client";

import Link from "next/link";
import { useActionState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TurnstileWidget } from "@/components/security/turnstile";
import { registerFreeAccount } from "./actions";
import { initialFreeRegistrationState } from "./state";

export function FreeRegistrationForm() {
  const [state, action, pending] = useActionState(
    registerFreeAccount,
    initialFreeRegistrationState,
  ) as [
    typeof initialFreeRegistrationState,
    (formData: FormData) => void,
    boolean,
  ];

  return (
    <form action={action} className="grid gap-5">
      <input
        type="text"
        name="website"
        tabIndex={-1}
        autoComplete="off"
        className="hidden"
        aria-hidden="true"
      />
      {state.status === "success" ? (
        <Alert tone="success">{state.message}</Alert>
      ) : null}
      {state.status === "error" ? (
        <Alert tone="error">{state.message}</Alert>
      ) : null}
      <div className="grid gap-2">
        <Label htmlFor="register-name">Full name</Label>
        <Input
          id="register-name"
          name="name"
          autoComplete="name"
          required
          minLength={2}
          maxLength={120}
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="register-email">Email address</Label>
        <Input
          id="register-email"
          name="email"
          type="email"
          autoComplete="email"
          required
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="register-password">Password</Label>
        <Input
          id="register-password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={12}
        />
        <p className="text-xs leading-5 text-slate-500">
          Use at least 12 characters. You will verify your email before signing
          in.
        </p>
      </div>
      <label className="flex items-start gap-3 text-sm leading-6 text-slate-700">
        <input
          type="checkbox"
          name="adultConfirmed"
          required
          className="mt-1 size-4 rounded border-slate-300 accent-red-600"
        />
        <span>
          I confirm that I am 18 years of age or older and have read the{" "}
          <Link href="/membership" className="font-semibold text-red-700 underline-offset-4 hover:underline">
            membership information
          </Link>
          . Free membership does not include governance voting rights or paid
          member benefits.
        </span>
      </label>
      <TurnstileWidget />
      <Button type="submit" disabled={pending}>
        {pending ? "Creating account…" : "Create free account"}
      </Button>
      <p className="text-sm text-slate-500">
        Applying for a paid tier?{" "}
        <Link href="/apply" className="font-semibold text-red-700 underline-offset-4 hover:underline">
          Use the membership application
        </Link>
        .
      </p>
    </form>
  );
}
