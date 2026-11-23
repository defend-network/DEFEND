import type { Metadata } from "next";
import { Suspense } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TwoFactorForm } from "./two-factor-form";

export const metadata: Metadata = {
  title: "Two-Factor Verification",
  robots: { index: false, follow: false },
};

export default function TwoFactorPage() {
  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Two-factor verification</CardTitle>
        <p className="text-sm leading-6 text-slate-500">
          Enter the six-digit code from your authenticator app.
        </p>
      </CardHeader>
      <CardContent>
        <Suspense fallback={<p className="text-sm text-slate-500">Loading…</p>}>
          <TwoFactorForm />
        </Suspense>
      </CardContent>
    </Card>
  );
}
