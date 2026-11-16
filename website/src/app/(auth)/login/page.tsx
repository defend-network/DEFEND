import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoginForm } from "./login-form";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Member Login",
  description: "Sign in to the DEFEND member portal.",
  robots: { index: false, follow: false },
};

export default function LoginPage() {
  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Member sign in</CardTitle>
        <p className="text-sm leading-6 text-slate-500">
          Use the email address associated with your approved membership
          application.
        </p>
      </CardHeader>
      <CardContent>
        <Suspense fallback={<p className="text-sm text-slate-500">Loadingâ€¦</p>}>
          <LoginForm />
        </Suspense>
        <p className="mt-6 border-t border-slate-100 pt-4 text-xs leading-5 text-slate-500">
          Not a member?{" "}
          <Link
            href="/apply"
            className="font-semibold text-red-700 underline-offset-4 hover:underline"
          >
            Apply for membership
          </Link>
          .
        </p>
      </CardContent>
    </Card>
  );
}
