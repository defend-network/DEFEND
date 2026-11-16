import type { Metadata } from "next";
import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ForgotPasswordForm } from "./forgot-password-form";

export const metadata: Metadata = {
  title: "Password Reset",
  robots: { index: false, follow: false },
};

export default function ForgotPasswordPage() {
  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Password reset</CardTitle>
        <p className="text-sm leading-6 text-slate-500">
          Enter the email address associated with your DEFEND account. If an
          account exists, a reset link will be sent.
        </p>
      </CardHeader>
      <CardContent className="grid gap-5">
        <ForgotPasswordForm />
        <p className="border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500">
          <Link href="/login" className="font-semibold text-red-700 underline-offset-4 hover:underline">
            Return to sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
