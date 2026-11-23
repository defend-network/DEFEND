import type { Metadata } from "next";
import Link from "next/link";

import { Container } from "@/components/ui/section";
import { EmailCodeForm } from "./email-code-form";

export const metadata: Metadata = {
  title: "Email Sign-In Code",
  robots: { index: false, follow: false },
};

export const dynamic = "force-dynamic";

export default function EmailCodePage() {
  return (
    <Container className="flex min-h-[70vh] items-center justify-center py-12">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-red-700">
            Member access
          </p>
          <h1 className="mt-3 text-3xl font-semibold">Sign in with email</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            We will send a six-digit verification code to your verified email
            address.
          </p>
        </div>
        <div className="rounded-[var(--radius-card)] border border-slate-200 bg-white p-6 shadow-sm">
          <EmailCodeForm />
        </div>
        <p className="mt-6 text-center text-sm text-slate-500">
          Prefer a password?{" "}
          <Link
            href="/login"
            className="font-semibold text-red-700 underline-offset-4 hover:underline"
          >
            Use password sign-in
          </Link>
        </p>
      </div>
    </Container>
  );
}
