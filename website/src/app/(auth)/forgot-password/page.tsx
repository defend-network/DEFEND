import type { Metadata } from "next";
import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { siteConfig } from "@/lib/config/site";

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
          Automated password reset will be available when the DEFEND email
          integration is configured.
        </p>
      </CardHeader>
      <CardContent className="grid gap-5">
        <Alert tone="info">
          Email delivery is not configured yet. Contact DEFEND at{" "}
          <a
            href={`mailto:${siteConfig.contactEmail}`}
            className="font-semibold underline underline-offset-4"
          >
            {siteConfig.contactEmail}
          </a>{" "}
          for account recovery.
        </Alert>
        <Button asChild variant="secondary">
          <Link href="/login">Return to sign in</Link>
        </Button>
      </CardContent>
    </Card>
  );
}
