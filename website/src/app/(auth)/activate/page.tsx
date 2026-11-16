import type { Metadata } from "next";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ActivationForm } from "./activation-form";

export const metadata: Metadata = {
  title: "Activate Account",
  robots: { index: false, follow: false },
};

export default function ActivatePage() {
  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Activate your DEFEND account</CardTitle>
        <p className="text-sm leading-6 text-slate-500">
          Set your password to finish creating your member account.
        </p>
      </CardHeader>
      <CardContent>
        <ActivationForm />
      </CardContent>
    </Card>
  );
}
